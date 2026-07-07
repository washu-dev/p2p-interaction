"""FastAPI app: serves the UI and the staged-pipeline API.

Run from gui/:
    uvicorn main:app --reload --app-dir backend --port 8000
"""
import hashlib
import json
import time
import uuid
from pathlib import Path

import config
import db
from auth import require_user
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from runner import get_runner
from stages import build_stages, overall_status

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
        overall, stages, err = runner.poll(job, job_dir(job["id"]))
        result = str(job_dir(job["id"]) / "result.png") if overall == "COMPLETED" else None
        db.update_job(job["id"], status=overall, stages=stages, error=err, result_path=result)
        job = db.get_job(job["id"])
    if job and job["status"] == "COMPLETED":
        _maybe_publish(job)
    return job


def _maybe_publish(job):
    """If the user consented, publish results to the shared library (idempotent)."""
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
    """Shared, opt-in results library — visible to any signed-in user."""
    if resultsdb is None:
        return {"results": [], "note": "results library not configured"}
    return {"results": resultsdb.list_results(kinase=kinase, target=target, q=q)}


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
