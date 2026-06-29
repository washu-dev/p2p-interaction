"""FastAPI app: serves the UI and the staged-pipeline API.

Run from gui/:
    uvicorn main:app --reload --app-dir backend --port 8000
"""
import hashlib
import json
import time
import uuid
from pathlib import Path

import auth as authmod
import config
import db
from auth import auth_config, require_user
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from runner import get_runner
from stages import build_stages, overall_status
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI(title="BindCraft GUI")

# Cross-origin access: required when the SPA (e.g. CloudFront) calls the API on a
# different origin (e.g. the ALB). Harmless when same-origin (list stays empty).
# allow_credentials=True so the session cookie is sent; that forbids "*", so we
# enumerate explicit origins via BINDGUI_CORS_ORIGINS.
if config.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.add_middleware(
    SessionMiddleware,
    secret_key=config.SESSION_SECRET,
    same_site=config.COOKIE_SAMESITE,
    https_only=config.COOKIE_SECURE,
)
runner = get_runner()
db.init_db()

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
    return job


@app.get("/api/config")
def get_config():
    return {
        "mode": config.BACKEND_MODE,
        "filters": config.list_filter_presets(),
        "advanced": config.list_advanced_presets(),
        "kinases": config.list_target_kinases(),
    }


@app.get("/api/auth/config")
def get_auth_config():
    """Public — tells the SPA whether login is required + the login URL."""
    return auth_config()


@app.get("/api/auth/login")
async def auth_login(request: Request):
    return await authmod.login(request)


@app.get("/api/auth/callback", name="auth_callback")
async def auth_callback(request: Request):
    return await authmod.callback(request)


@app.get("/api/auth/logout")
async def auth_logout(request: Request):
    return await authmod.logout(request)


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


# The UI is served from the same origin as the API.
app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True), name="ui")
