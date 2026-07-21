"""FastAPI app: serves the UI and the staged-pipeline API.

Run from gui/:
    uvicorn main:app --reload --app-dir backend --port 8000
"""
import asyncio
import hashlib
import io
import json
import time
import uuid
import zipfile
from pathlib import Path

import config
import db
import kinase_families
import notify
import targetlibrary
import uniprot
from auth import require_user
from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from runner import get_runner
from stages import build_stages, overall_status

# Log the effective config and validate it before anything else starts. Phase 1
# is WARN-ONLY: problems are logged but don't abort, so a rollout is never
# blocked while the per-env config files are still being populated. Flip to
# fail-fast (raise SystemExit) once config/<env>.json is authoritative.
print(config.effective_config_log())
_config_problems = config.validate()
for _p in _config_problems:
    print(f"[config] WARNING: {_p}")

app = FastAPI(title="BindCraft GUI")

# Allow the Vite dev server and any configured origins to call the API.
cors_origins = list(config.CORS_ORIGINS) + ["http://localhost:5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
runner = get_runner()
db.init_db()
targetlibrary.init_library_db()
try:
    import resultsdb
    resultsdb.init_results_db()
except Exception as _e:  # noqa: BLE001 — results library is optional; never block startup
    resultsdb = None
    print(f"[results-library] disabled: {_e}")

FASTA_EXTS = {".fasta", ".fa", ".faa", ".seq"}
PDB_EXTS = {".pdb", ".ent"}


def job_dir(job_id: str) -> Path:
    return config.JOBS_DIR / job_id


def params_key(file_sha: str, settings: dict) -> str:
    canon = json.dumps({"file": file_sha, "settings": settings}, sort_keys=True)
    return hashlib.sha256(canon.encode()).hexdigest()


def refresh(job):
    """Re-poll the runner for unfinished jobs and persist any change."""
    if job and job["status"] in ("PENDING", "RUNNING"):
        try:
            overall, stages, err = runner.poll(job, job_dir(job["id"]))
            result = str(job_dir(job["id"]) / "result.png") if overall == "COMPLETED" else None
            db.update_job(job["id"], status=overall, stages=stages, error=err, result_path=result)
            job = db.get_job(job["id"])
        except Exception as e:  # noqa: BLE001 — a poll failure must not 500 the whole list
            print(f"[poll] {job['id']} poll failed, leaving as-is: {e}")
    if job and job["status"] == "COMPLETED":
        _maybe_publish(job)
    if job and job["status"] in ("COMPLETED", "FAILED"):
        _maybe_notify(job)
    return job


def _maybe_publish(job):
    """If the user consented, publish results to the binder library (idempotent)."""
    if resultsdb is None or not job["settings"].get("make_public"):
        return
    d = job_dir(job["id"])
    flag = d / "published.flag"
    sel = d / "selectivity.json"
    if flag.exists() or not sel.exists():
        return
    try:
        design = json.loads((d / "design_result.json").read_text()) if (d / "design_result.json").exists() else {}
        selectivity = json.loads(sel.read_text())
        resultsdb.publish(job, design, selectivity, submitted_by=job["settings"].get("submitted_by") or "unknown")
        flag.write_text("1")
    except Exception as e:  # noqa: BLE001 — never let publishing break polling
        print(f"[results-library] publish failed for {job['id']}: {e}")


def _maybe_notify(job):
    """Email the submitter once when a run reaches COMPLETED/FAILED (idempotent)."""
    d = job_dir(job["id"])
    flag = d / "notified.flag"
    if flag.exists():
        return
    to = (job.get("settings") or {}).get("submitted_by") or ""
    if "@" not in to:
        return
    try:
        if job["status"] == "COMPLETED":
            notify.notify_completed(job, d, to)
        else:
            notify.notify_failed(job, to)
        flag.write_text("1")
    except Exception as e:  # noqa: BLE001 — a broken mailer must never break job polling
        print(f"[notify] failed for {job['id']}: {e}")


async def _background_poll_loop():
    """Refresh unfinished jobs on a timer, independent of any browser polling —
    otherwise a job that finishes with no open browser tab never triggers its
    completion/failure email."""
    while True:
        try:
            for j in db.list_jobs():
                if j["status"] in ("PENDING", "RUNNING"):
                    refresh(j)
        except Exception as e:  # noqa: BLE001 — one bad sweep must not kill the loop
            print(f"[poll-loop] sweep failed: {e}")
        await asyncio.sleep(config.BACKGROUND_POLL_SEC)


@app.on_event("startup")
async def _start_background_poller():
    asyncio.create_task(_background_poll_loop())


@app.get("/api/health")
def health():
    """ALB target-group health check. Always 200 so a DB outage doesn't pull
    every task out of rotation — the `db` field reports connectivity instead.
    """
    return {
        "status": "ok",
        "git_sha": config.GIT_SHA,
        "deployed_at": config.BUILD_TIME,
        "backend_mode": config.BACKEND_MODE,
        "db": resultsdb.ping() if resultsdb else {"backend": None, "connected": False,
                                                  "error": "results library not configured"},
    }


@app.get("/api/binders")
def list_binders(user: dict = Depends(require_user)):
    """Debug endpoint: joins binders + artifacts + selectivity straight from
    the DB, to verify the app is actually reading RDS (not the SQLite fallback).
    """
    if resultsdb is None:
        raise HTTPException(503, "results library not configured")
    try:
        return {"binders": resultsdb.list_binders_full()}
    except Exception as e:  # noqa: BLE001 — surface the real DB error to the caller
        raise HTTPException(500, f"query failed: {e}") from e


@app.get("/api/config")
def get_config():
    return {
        "mode": config.BACKEND_MODE,
        "filters": config.list_filter_presets(),
        "advanced": config.list_advanced_presets(),
        "kinases": config.list_target_kinases(),
    }


@app.get("/api/me")
def me(user: dict = Depends(require_user)):
    return user


# ---------------------------------------------------------------------------
# Kinase search (UniProt) + shared target library
# ---------------------------------------------------------------------------
@app.get("/api/uniprot/search")
def uniprot_search(q: str, organism: str = "Homo sapiens", size: int = 5, user: dict = Depends(require_user)):
    """Search UniProtKB by gene/protein name (e.g. LATS1, NDR1).

    An empty `organism` searches across all species — used by the Simple
    search so users can pick the right origin themselves.
    """
    if not q.strip():
        raise HTTPException(400, "q is required")
    try:
        return {"candidates": uniprot.search(q.strip(), organism.strip(), size=max(1, min(size, 20)))}
    except uniprot.UniprotError as e:
        raise HTTPException(502, str(e)) from None


@app.post("/api/targets/fetch")
def targets_fetch(payload: dict = Body(...), user: dict = Depends(require_user)):
    """Download the FASTA for a chosen UniProt accession and save it to the
    shared target library so the next person can reuse it without re-fetching."""
    accession = (payload.get("accession") or "").strip()
    name = (payload.get("name") or accession).strip()
    organism = (payload.get("organism") or "").strip()
    if not accession:
        raise HTTPException(400, "accession is required")
    try:
        fasta_text = uniprot.fetch_fasta(accession)
    except uniprot.UniprotError as e:
        raise HTTPException(502, str(e)) from None
    row = targetlibrary.add_target(
        name=name, input_type="fasta", data=fasta_text.encode("utf-8"),
        source="uniprot", submitted_by=user.get("preferred_username") or user.get("sub") or "unknown",
        accession=accession, organism=organism,
    )
    return {"target": row, "fasta_text": fasta_text}


@app.post("/api/targets/upload")
async def targets_upload(
    file: UploadFile = File(...),
    name: str = Form(""),
    user: dict = Depends(require_user),
):
    """Directly upload a FASTA or PDB target into the shared library."""
    ext = Path(file.filename or "").suffix.lower()
    if ext in FASTA_EXTS:
        input_type = "fasta"
    elif ext in PDB_EXTS:
        input_type = "pdb"
    else:
        raise HTTPException(400, f"unsupported file type '{ext}'; upload .fasta or .pdb")
    data = await file.read()
    row = targetlibrary.add_target(
        name=(name or Path(file.filename).stem).strip(), input_type=input_type, data=data,
        source="upload", submitted_by=user.get("preferred_username") or user.get("sub") or "unknown",
    )
    return {"target": row}


@app.get("/api/targets")
def targets_list(q: str | None = None, input_type: str | None = None, user: dict = Depends(require_user)):
    """Browse the shared target library (fetched-from-UniProt + directly-uploaded files)."""
    return {"targets": targetlibrary.list_targets(q=q, input_type=input_type)}


@app.get("/api/targets/{tid}/file")
def targets_file(tid: str, user: dict = Depends(require_user)):
    row = targetlibrary.get_target(tid)
    if not row:
        raise HTTPException(404, "target not found")
    data = targetlibrary.read_file(tid, row["input_type"])
    media = "text/plain" if row["input_type"] == "fasta" else "chemical/x-pdb"
    return Response(content=data, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{row["file_name"]}"'
    })


@app.post("/api/jobs")
async def create_job(
    file: UploadFile = File(...),
    payload: str = Form(...),
    user: dict = Depends(require_user),
):
    """Multipart: the target file + a JSON `payload` with name/settings/targets."""
    try:
        p = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(400, "payload is not valid JSON") from None

    ext = Path(file.filename or "").suffix.lower()
    if ext in FASTA_EXTS:
        input_type = "fasta"
    elif ext in PDB_EXTS:
        input_type = "pdb"
    else:
        raise HTTPException(400, f"unsupported file type '{ext}'; upload .fasta or .pdb")

    data = await file.read()
    file_sha = hashlib.sha256(data).hexdigest()

    settings = {
        "binder_name": (p.get("binder_name") or "binder").strip(),
        "chains": (p.get("chains") or "A").strip(),
        "target_hotspot_residues": str(p.get("target_hotspot_residues") or "").strip(),
        "length_min": int(p.get("length_min") or 65),
        "length_max": int(p.get("length_max") or 150),
        "number_of_final_designs": int(p.get("number_of_final_designs") or 100),
        "filters_preset": p.get("filters_preset") or "default_filters",
        "advanced_preset": p.get("advanced_preset") or "default_4stage_multimer",
        "targets": p.get("targets") or [],
    }
    key = params_key(file_sha, settings)
    # Consent, submitter and the RIS/SLURM account are recorded AFTER the key so
    # they don't affect dedup (they don't change the scientific result).
    settings["make_public"] = bool(p.get("make_public"))
    settings["submitted_by"] = user.get("preferred_username") or user.get("sub") or "unknown"
    settings["slurm_account"] = (p.get("slurm_account") or "").strip()
    settings["max_runtime_hours"] = max(1, int(p.get("max_runtime_hours") or 15))

    if not p.get("force"):
        cached = db.find_cached(key)
        if cached:
            return {"cache_hit": True, "job": cached}

    jid = uuid.uuid4().hex
    d = job_dir(jid)
    d.mkdir(parents=True, exist_ok=True)

    # Save the uploaded target as target.fasta or target.pdb.
    target_file = d / ("target.fasta" if input_type == "fasta" else "target.pdb")
    target_file.write_bytes(data)
    (d / "targets.txt").write_text("\n".join(settings["targets"]) + "\n")

    # Generate the BindCraft target settings json from the form.
    (d / "settings_target.json").write_text(
        json.dumps(
            {
                "design_path": str(d / "bindcraft_out") + "/",
                "binder_name": settings["binder_name"],
                "starting_pdb": str(d / "target.pdb"),
                "chains": settings["chains"],
                "target_hotspot_residues": settings["target_hotspot_residues"],
                "lengths": [settings["length_min"], settings["length_max"]],
                "number_of_final_designs": settings["number_of_final_designs"],
            },
            indent=2,
        )
    )

    now = time.time()
    job = {
        "id": jid,
        "name": p.get("name") or settings["binder_name"],
        "status": "PENDING",
        "params_key": key,
        "mode": config.BACKEND_MODE,
        "input_type": input_type,
        "target_name": p.get("target_name") or Path(file.filename).stem,
        "settings": settings,
        "stages": build_stages(input_type),
        "result_path": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
    }
    db.create_job(job)
    try:
        stages = runner.submit(job, d)
        db.update_job(jid, stages=stages, status=overall_status(stages))
    except Exception as e:  # noqa: BLE001 — surface submission failures to the UI
        db.update_job(jid, status="FAILED", error=f"submit failed: {e}")
    return {"cache_hit": False, "job": db.get_job(jid)}


@app.get("/api/library")
def library(
    kinase: str | None = None,
    target: str | None = None,
    q: str | None = None,
    user: dict = Depends(require_user),
):
    """Binder library — opt-in published binders, visible to any signed-in user."""
    if resultsdb is None:
        return {"results": [], "note": "binder library not configured"}
    return {"results": resultsdb.list_results(kinase=kinase, target=target, q=q)}


@app.get("/api/kinase-families")
def kinase_family_map(user: dict = Depends(require_user)):
    """Manning kinome groups → member kinases, for the family selector."""
    return {"groups": {g: kinase_families.kinases_in(g) for g in kinase_families.groups()}}


def _library_summary(b: dict) -> str:
    lines = [
        "BindCraft Binder Library — Summary",
        "=" * 50, "",
        f"Binder name:     {b.get('binder_name', '')}",
        f"Target:          {b.get('target_name', '')}",
        f"Composite score: {b.get('composite_score', '')}",
        f"Submitted by:    {b.get('submitted_by', '')}",
        f"Sequence:        {b.get('binder_sequence', '')}",
    ]
    dm = b.get("design_metrics") or {}
    if dm:
        lines += ["", "Design metrics", "-" * 50]
        lines += [f"{k}: {v}" for k, v in dm.items()]
    sel = b.get("selectivity") or []
    if sel:
        lines += ["", "Selectivity (average ipTM, most cross-reactive first)", "-" * 50]
        for s in sorted(sel, key=lambda x: (x.get("avg_iptm") or 0), reverse=True):
            lines += [f"{s['kinase']}: {s.get('avg_iptm')}"]
    return "\n".join(str(x) for x in lines) + "\n"


def _avg_graph_png(binder: dict, family: str | None) -> bytes:
    """Return the cached avg-ipTM graph for (binder, family), generating + caching
    it in RDS on first request so repeat views need no regeneration."""
    key = "ALL" if not family or family.upper() == "ALL" else family
    kind = f"graph_avg_{key}"
    cached = resultsdb.get_artifact(binder["id"], kind)
    if cached and cached.get("content"):
        return cached["content"]
    import graphs  # lazy: pulls in matplotlib only when a graph is actually needed
    png = graphs.avg_iptm_png(
        binder["target_name"], binder["selectivity"],
        family=None if key == "ALL" else key,
    )
    resultsdb.put_artifact(binder["id"], kind, f"iptm_avg_{key}.png", "image/png", png)
    return png


@app.get("/api/library/{binder_id}/graph.png")
def library_graph(binder_id: str, family: str = "ALL", user: dict = Depends(require_user)):
    """Average-ipTM graph for a binder, whole panel (family=ALL) or one Manning
    family. Generated on demand and cached back into RDS."""
    if resultsdb is None:
        raise HTTPException(503, "binder library not configured")
    binder = resultsdb.get_binder(binder_id)
    if not binder:
        raise HTTPException(404, "binder not found")
    png = _avg_graph_png(binder, family)
    return Response(content=png, media_type="image/png")


@app.get("/api/library/{binder_id}/bundle.zip")
def library_bundle(binder_id: str, user: dict = Depends(require_user)):
    """Zip a binder's deliverables from RDS: binder PDB + sequence, avg-ipTM plot,
    logs (if stored), and a summary — mirroring the run Download bundle."""
    if resultsdb is None:
        raise HTTPException(503, "binder library not configured")
    binder = resultsdb.get_binder(binder_id)
    if not binder:
        raise HTTPException(404, "binder not found")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        pdb = resultsdb.get_artifact(binder_id, "binder_structure")
        if pdb and pdb.get("content"):
            z.writestr("binder.pdb", pdb["content"])
        if binder.get("binder_sequence"):
            z.writestr(
                "binder.fasta",
                f">{binder.get('binder_name', 'binder')}\n{binder['binder_sequence']}\n",
            )
        z.writestr("iptm_plot.png", _avg_graph_png(binder, "ALL"))
        logs = resultsdb.get_artifact(binder_id, "logs")
        z.writestr(
            "run_logs.txt",
            logs["content"].decode(errors="replace")
            if logs and logs.get("content") else "(logs not available for library binders)\n",
        )
        z.writestr("summary.txt", _library_summary(binder))

    buf.seek(0)
    safe = "".join(c for c in (binder.get("binder_name") or binder_id) if c.isalnum() or c in "-_") or binder_id
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="binder_{safe}.zip"'},
    )


@app.get("/api/jobs")
def list_jobs(user: dict = Depends(require_user)):
    return {"jobs": [refresh(j) for j in db.list_jobs()]}


@app.get("/api/jobs/{jid}")
def get_job(jid: str, user: dict = Depends(require_user)):
    job = db.get_job(jid)
    if not job:
        raise HTTPException(404, "job not found")
    return refresh(job)


@app.get("/api/jobs/{jid}/result.png")
def result_png(jid: str, user: dict = Depends(require_user)):
    p = job_dir(jid) / "result.png"
    if not p.exists():
        raise HTTPException(404, "result not ready")
    return FileResponse(p, media_type="image/png")


@app.get("/api/jobs/{jid}/logs")
def logs(jid: str, user: dict = Depends(require_user)):
    d = job_dir(jid)
    if not d.exists():
        raise HTTPException(404, "job not found")
    text = ""
    for f in sorted(d.glob("*.log")):
        text += f"===== {f.name} =====\n{f.read_text(errors='replace')}\n"
    return {"logs": text[-40000:] or "(no logs yet)"}


def _run_summary(job: dict, design: dict) -> str:
    s = job.get("settings", {})
    lines = [
        "BindCraft Selective Binder Platform — Run Summary",
        "=" * 50, "",
        f"Run name:        {job.get('name', '')}",
        f"Target:          {job.get('target_name', '')} ({job.get('input_type', '')})",
        f"Status:          {job.get('status', '')}",
        f"Binder name:     {s.get('binder_name', '')}",
        f"Chains:          {s.get('chains', '')}",
        f"Hotspots:        {s.get('target_hotspot_residues') or '(none)'}",
        f"Binder length:   {s.get('length_min')}-{s.get('length_max')}",
        f"Final designs:   {s.get('number_of_final_designs')}",
        f"Filters preset:  {s.get('filters_preset', '')}",
        f"Advanced preset: {s.get('advanced_preset', '')}",
        f"Kinase panel:    {', '.join(s.get('targets') or [])}",
        "",
        f"Stages:          {'  '.join(st['key'] + ':' + st['status'] for st in job.get('stages', []))}",
    ]
    if design:
        lines += [
            "", "Top binder", "-" * 50,
            f"Name:            {design.get('binder_name', '')}",
            f"Composite score: {design.get('composite_score', '')}",
            f"Sequence:        {design.get('binder_sequence', '')}",
        ]
    return "\n".join(lines) + "\n"


@app.get("/api/jobs/{jid}/bundle.zip")
def bundle(jid: str, user: dict = Depends(require_user)):
    """Zip the deliverables: binder PDB + sequence, ipTM plot, logs, summary."""
    job = db.get_job(jid)
    d = job_dir(jid)
    if not job or not d.exists():
        raise HTTPException(404, "job not found")

    design = {}
    dr = d / "design_result.json"
    if dr.exists():
        try:
            design = json.loads(dr.read_text())
        except json.JSONDecodeError:
            design = {}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        pdb = d / "top_binder.pdb"
        if pdb.exists():
            z.write(pdb, "binder.pdb")
        fasta = d / "top_binder.fasta"
        if fasta.exists():
            z.write(fasta, "binder.fasta")
        elif design.get("binder_sequence"):
            z.writestr("binder.fasta", f">{design.get('binder_name', 'binder')}\n{design['binder_sequence']}\n")
        target_pdb = d / "target.pdb"
        if target_pdb.exists():
            z.write(target_pdb, "target.pdb")
        target_fasta = d / "target.fasta"
        if target_fasta.exists():
            z.write(target_fasta, "target.fasta")
        png = d / "result.png"
        if png.exists():
            z.write(png, "iptm_plot.png")
        logs_text = ""
        for f in sorted(d.glob("*.log")):
            logs_text += f"===== {f.name} =====\n{f.read_text(errors='replace')}\n"
        z.writestr("run_logs.txt", logs_text or "(no logs)")
        z.writestr("summary.txt", _run_summary(job, design))

    buf.seek(0)
    safe = "".join(c for c in (job.get("target_name") or jid) if c.isalnum() or c in "-_") or jid
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="binder_{safe}.zip"'},
    )


@app.post("/api/jobs/{jid}/cancel")
def cancel(jid: str, user: dict = Depends(require_user)):
    job = db.get_job(jid)
    if not job:
        raise HTTPException(404, "job not found")
    stages = runner.cancel(job, job_dir(jid))
    db.update_job(jid, stages=stages, status="CANCELLED")
    return db.get_job(jid)


# Serve the built React app when present (always in the Docker image). When it's
# missing (local API-only runs / Vite dev on :5173), skip the mount so startup
# doesn't fail — the API still works and Vite proxies /api in dev.
if config.FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True), name="ui")
