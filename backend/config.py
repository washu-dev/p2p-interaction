"""Central configuration for the BindCraft GUI backend.

Values are resolved by config_loader.get() with precedence (high → low):
process env var > backend/config.json (secrets from fetch_secrets.py) >
backend/config/<env>.json (committed OPEN per-env values, selected by
BINDGUI_ENV) > code default. So a whole environment's non-secret config lives in
one committed file, its secrets in AWS Secrets Manager, and the task definition
only needs BINDGUI_ENV. See config_loader.py and configschema.py.

  * BINDGUI_BACKEND=mock   -> staged jobs are simulated on a laptop.
  * BINDGUI_BACKEND=slurm  -> real sbatch chain on the cluster login node.
  * BINDGUI_BACKEND=ssh    -> backend off-cluster, drives the login node via Paramiko.

A few values are read ONLY from the environment (never a config file): GIT_SHA
(baked at image build), SLURM_ACCOUNT, and the SSH credential trio SSH_KEY /
SSH_KEY_PASSPHRASE / SSH_KNOWN_HOSTS_FILE (materialized at runtime by
fetch_secrets.py / the ECS task definition).

validate() (fail-fast, mode-aware) and effective_config_log() (redacted
startup dump) are called from main.py at startup.
"""
from pathlib import Path

import config_loader
import configschema

BASE_DIR = Path(__file__).resolve().parent          # gui/backend
GUI_DIR = BASE_DIR.parent                            # gui
REPO_DIR = GUI_DIR.parent                            # BindCraft repo root
PIPELINE_DIR = BASE_DIR / "pipeline"
# Single UI: the built React app (web/dist). Served by FastAPI when present
# (always in the Docker image; locally requires `npm run build` or use Vite dev).
FRONTEND_DIR = GUI_DIR / "web" / "dist"

# Selected environment (dev|staging|prod); picks the committed open config file.
ENV = config_loader.ENV


def _setting(name: str, default=""):
    """Resolve via config_loader (env > config.json > config/<env>.json > default)."""
    return config_loader.get(name, default)


def _env_only(name: str, default=""):
    """Resolve from the environment only (skips both JSON layers)."""
    return config_loader.get(name, default, env_only=True)


# "mock" | "slurm" | "ssh"
BACKEND_MODE = str(_setting("BINDGUI_BACKEND", "mock")).lower()

# Baked in at image build time (see Dockerfile ARGs) so /api/health can report
# what's actually deployed. GIT_SHA is env-only (never a config file).
GIT_SHA = _env_only("GIT_SHA", "unknown")
BUILD_TIME = _setting("BUILD_TIME", "unknown")

DATA_DIR = Path(_setting("BINDGUI_DATA_DIR", GUI_DIR / "data"))
JOBS_DIR = DATA_DIR / "jobs"
DB_PATH = Path(_setting("BINDGUI_DB", DATA_DIR / "bindgui.sqlite"))

# ---------------------------------------------------------------------------
# Cluster / SLURM settings (used when BACKEND_MODE == "slurm")
# ---------------------------------------------------------------------------
# SLURM_ACCOUNT is env-only (per-deployment, set on the task definition).
SLURM_ACCOUNT = _env_only("BINDGUI_SLURM_ACCOUNT", "compute2-rmitra")
SLURM_PARTITION = _setting("BINDGUI_SLURM_PARTITION", "general-gpu")

# BindCraft checkout (holds bindcraft.py + settings_filters/ + settings_advanced/).
BINDCRAFT_DIR = Path(_setting("BINDGUI_BINDCRAFT_DIR", REPO_DIR))
SETTINGS_FILTERS_DIR = BINDCRAFT_DIR / "settings_filters"
SETTINGS_ADVANCED_DIR = BINDCRAFT_DIR / "settings_advanced"

# Directory holding one <kinase>.fasta per target in the selectivity panel.
TARGET_FASTA_DIR = _setting("BINDGUI_TARGET_FASTA_DIR", "../kinase_sequence")

# Prepended to PATH so `colabfold_batch` is found inside jobs.
COLABFOLD_BIN_DIR = _setting(
    "BINDGUI_COLABFOLD_BIN",
    "/storage1/fs1/rmitra/Active/minibinders/d.mingyue/localcolabfold/.pixi/envs/default/bin",
)

# micromamba env name + root prefix used by the bindcraft stage.
MICROMAMBA_ENV = _setting("BINDGUI_MICROMAMBA_ENV", "BindCraft")
MAMBA_ROOT = _setting("BINDGUI_MAMBA_ROOT", str(BINDCRAFT_DIR / "Y"))

# ---------------------------------------------------------------------------
# Mock-mode settings
# ---------------------------------------------------------------------------
MOCK_RESULT_PNG = Path(_setting("BINDGUI_MOCK_PNG", REPO_DIR / "iptm_scores.png"))
MOCK_TARGET_PDB = Path(_setting("BINDGUI_MOCK_PDB", REPO_DIR / "example" / "PDL1.pdb"))
# Seconds each simulated stage takes (fold, design, profile).
MOCK_STAGE_SEC = int(_setting("BINDGUI_MOCK_STAGE_SEC", "4"))

# The curated selectivity panel. These names MUST match the <name>.fasta files in
# BINDGUI_TARGET_FASTA_DIR on the cluster: the profile stage builds one
# binder:kinase complex per file and labels the plot by these names.
SAMPLE_KINASES = [
    "PDL1", "LATS1", "LATS2", "NDR1", "NDR2", "ROCK1", "ROCK2", "Map4k4",
]

# ---------------------------------------------------------------------------
# SSH / remote mode  (BACKEND_MODE == "ssh")
# Backend hosted off-cluster (AWS) drives the login node via Paramiko + an RSA
# key pair. In this mode BINDCRAFT_DIR / TARGET_FASTA_DIR / COLABFOLD_BIN /
# MAMBA_ROOT above must be CLUSTER paths (set them via config.json or env).
# ---------------------------------------------------------------------------
SSH_HOST = _setting("BINDGUI_SSH_HOST", "")
SSH_PORT = int(_setting("BINDGUI_SSH_PORT", "22"))
SSH_USER = _setting("BINDGUI_SSH_USER", "")
# The SSH credential trio is env-only: SSH_KEY / SSH_KNOWN_HOSTS_FILE are file
# paths fetch_secrets.py writes at container startup, and the passphrase is a
# secret — none of these belong in config.json.
SSH_KEY = _env_only("BINDGUI_SSH_KEY", "")  # path to the PRIVATE key on the host
SSH_KEY_PASSPHRASE = _env_only("BINDGUI_SSH_KEY_PASSPHRASE", "") or None
SSH_KNOWN_HOSTS_FILE = _env_only("BINDGUI_SSH_KNOWN_HOSTS_FILE", "")
# Per-job scratch root ON THE CLUSTER (job subdirs + uploaded pipeline live here).
REMOTE_DIR = _setting(
    "BINDGUI_REMOTE_DIR",
    f"/storage1/fs1/rmitra/Active/minibinders/{SSH_USER or 'USER'}/bindgui",
)
REMOTE_PIPELINE_DIR = REMOTE_DIR + "/pipeline"

# ---------------------------------------------------------------------------
# Web user auth — WashU SSO / Microsoft Entra ID, SPA + bearer token.
# The React SPA signs in with MSAL.js and sends `Authorization: Bearer <token>`;
# the backend only VALIDATES the JWT (see auth.py). There is no server-side
# authorization-code flow, no client secret, and no session cookie.
# Disabled by default so mock/dev needs no login.
# ---------------------------------------------------------------------------
AUTH_ENABLED = str(_setting("BINDGUI_AUTH_ENABLED", "false")).lower() == "true"

# CORS — comma-separated web origins allowed to call the API from the browser.
# Needed when the SPA and API are on different origins (cross-origin); the SPA
# sends the bearer token in the Authorization header.
# e.g. BINDGUI_CORS_ORIGINS="https://d5j3l1rgzmla.cloudfront.net"
CORS_ORIGINS = [o.strip() for o in str(_setting("BINDGUI_CORS_ORIGINS", "")).split(",") if o.strip()]

# ---------------------------------------------------------------------------
# Email notifications on job completion/failure — SendGrid.
# Runs (fold+design+profile chained) can take hours; most users won't sit and
# watch. Blank SENDGRID_API_KEY/EMAIL_SENDER disables real sending —
# notify.py logs instead, so mock-mode dev needs no SendGrid setup.
# ---------------------------------------------------------------------------
SENDGRID_API_KEY = _setting("BINDGUI_SENDGRID_API_KEY", "")
# Not secrets — safe to default in code. Still overridable via config.json/env.
EMAIL_SENDER = _setting("BINDGUI_EMAIL_SENDER", "di2accelerator@wustl.edu")
# Link back to the SPA, included in notification emails. Not auth-related —
# just where a user should click to see their run.
APP_URL = str(_setting("BINDGUI_APP_URL", "https://d5j3l1rgzmla.cloudfront.net")).rstrip("/")

# How often the backend checks unfinished jobs on its own, independent of any
# browser polling — otherwise a completed/failed job with no open browser
# tab never triggers its email.
BACKGROUND_POLL_SEC = int(_setting("BINDGUI_BACKGROUND_POLL_SEC", "20"))

# ---------------------------------------------------------------------------
# Binder library — opt-in public store of binder + selectivity results.
# Postgres (RDS) in production; a local SQLite file for dev when DB_HOST is unset.
# (DB_HOST tolerates a trailing slash, which RDS console output sometimes adds.)
# The DB_* keys use bare names (no BINDGUI_ prefix) — fetch_secrets.py writes the
# same names into config.json from the grouped MiniBinders/database/* secrets.
# ---------------------------------------------------------------------------
DB_HOST = str(_setting("DB_HOST")).rstrip("/")
DB_PORT = int(_setting("DB_PORT", "5432"))
DB_USER = _setting("DB_USER")
DB_PASSWORD = _setting("DB_PASSWORD")
DB_NAME = _setting("DB_NAME")
RESULTS_SQLITE = Path(_setting("BINDGUI_RESULTS_SQLITE", DATA_DIR / "results.sqlite"))

# ---------------------------------------------------------------------------
# Shared target library — FASTA/PDB files (fetched from UniProt or uploaded
# directly) that any signed-in user can search and reuse as a pipeline input,
# instead of re-fetching/re-uploading a target someone already added.
# Same Postgres-in-prod / SQLite-in-dev split as the results library above.
# ---------------------------------------------------------------------------
LIBRARY_TARGETS_DIR = DATA_DIR / "library_targets"
LIBRARY_SQLITE = Path(_setting("BINDGUI_LIBRARY_SQLITE", DATA_DIR / "library.sqlite"))

# Entra identifiers for bearer-token validation (auth.py). The SPA is a PUBLIC
# client (PKCE, no secret); the backend needs only the tenant (to build the
# JWKS / issuer URL) and the app/client id (the intended token audience).
ENTRA_TENANT_ID = _setting("BINDGUI_ENTRA_TENANT_ID", "")
ENTRA_CLIENT_ID = _setting("BINDGUI_ENTRA_CLIENT_ID", "")
AUTHORITY = f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LIBRARY_TARGETS_DIR.mkdir(parents=True, exist_ok=True)
JOBS_DIR.mkdir(parents=True, exist_ok=True)


def _list_jsons(d: Path):
    return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []


def list_filter_presets():
    return _list_jsons(SETTINGS_FILTERS_DIR) or ["default_filters"]


def list_advanced_presets():
    return _list_jsons(SETTINGS_ADVANCED_DIR) or ["default_4stage_multimer"]


def list_target_kinases():
    d = Path(TARGET_FASTA_DIR)
    if BACKEND_MODE == "slurm" and d.is_dir():
        names = sorted(p.stem for p in d.glob("*.fasta"))
        if names:
            return names
    return SAMPLE_KINASES


# ---------------------------------------------------------------------------
# Startup validation + effective-config logging (called from main.py).
# ---------------------------------------------------------------------------
def validate() -> list[str]:
    """Fail-fast, mode-aware config checks. Returns problems (empty == OK)."""
    return configschema.validate(
        mode=BACKEND_MODE,
        env=ENV,
        get=lambda name: str(config_loader.get(name, "")),
    )


def effective_config_log() -> str:
    """A redacted table of every resolved setting and where it came from, so a
    misconfiguration (e.g. an identity key falling through to ⚠ DEFAULT) is
    obvious in the container logs. Sensitive values are never printed."""
    rows = []
    for name in sorted(config_loader.resolved()):
        value, src = config_loader.resolved()[name]
        if name in configschema.SENSITIVE:
            shown = f"set (len {len(value)})" if value else "MISSING"
        else:
            shown = value if value != "" else "(empty)"
        flag = " ⚠" if src == "DEFAULT" and name not in configschema.BENIGN_DEFAULTS else ""
        rows.append(f"  {name:<32} = {shown:<48} [{src}]{flag}")
    return f"[config] env={ENV} backend={BACKEND_MODE} — effective settings:\n" + "\n".join(rows)
