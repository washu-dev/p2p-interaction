"""Central configuration for the BindCraft GUI backend.

Override anything via environment variables so the same code runs in two modes:

  * BINDGUI_BACKEND=mock   -> staged jobs are simulated on a laptop.
  * BINDGUI_BACKEND=slurm  -> real sbatch chain on the cluster login node.
"""
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent          # gui/backend
GUI_DIR = BASE_DIR.parent                            # gui
REPO_DIR = GUI_DIR.parent                            # BindCraft repo root
PIPELINE_DIR = BASE_DIR / "pipeline"
# Single UI: the built React app (web/dist). Served by FastAPI when present
# (always in the Docker image; locally requires `npm run build` or use Vite dev).
FRONTEND_DIR = GUI_DIR / "web" / "dist"

# "mock"  -> simulate jobs locally (laptop dev)
# "slurm" -> backend runs ON the login node, submits via local sbatch
# "ssh"   -> backend runs OFF-cluster (e.g. AWS), drives the login node via Paramiko
BACKEND_MODE = os.environ.get("BINDGUI_BACKEND", "mock").lower()

DATA_DIR = Path(os.environ.get("BINDGUI_DATA_DIR", GUI_DIR / "data"))
JOBS_DIR = DATA_DIR / "jobs"
DB_PATH = Path(os.environ.get("BINDGUI_DB", DATA_DIR / "bindgui.sqlite"))

# ---------------------------------------------------------------------------
# Cluster / SLURM settings (used when BACKEND_MODE == "slurm")
# ---------------------------------------------------------------------------
SLURM_ACCOUNT = os.environ.get("BINDGUI_SLURM_ACCOUNT", "compute2-rmitra")
SLURM_PARTITION = os.environ.get("BINDGUI_SLURM_PARTITION", "general-gpu")

# BindCraft checkout (holds bindcraft.py + settings_filters/ + settings_advanced/).
BINDCRAFT_DIR = Path(os.environ.get("BINDGUI_BINDCRAFT_DIR", REPO_DIR))
SETTINGS_FILTERS_DIR = BINDCRAFT_DIR / "settings_filters"
SETTINGS_ADVANCED_DIR = BINDCRAFT_DIR / "settings_advanced"

# Directory holding one <kinase>.fasta per target in the selectivity panel.
TARGET_FASTA_DIR = os.environ.get("BINDGUI_TARGET_FASTA_DIR", "../kinase_sequence")

# Prepended to PATH so `colabfold_batch` is found inside jobs.
COLABFOLD_BIN_DIR = os.environ.get(
    "BINDGUI_COLABFOLD_BIN",
    "/storage1/fs1/rmitra/Active/minibinders/d.mingyue/localcolabfold/.pixi/envs/default/bin",
)

# micromamba env name + root prefix used by the bindcraft stage.
# MAMBA_ROOT defaults to <BindCraft>/Y to match your bindcraft.slurm CONDA_BASE;
# override BINDGUI_MAMBA_ROOT if your env root lives elsewhere.
MICROMAMBA_ENV = os.environ.get("BINDGUI_MICROMAMBA_ENV", "BindCraft")
MAMBA_ROOT = os.environ.get("BINDGUI_MAMBA_ROOT", str(BINDCRAFT_DIR / "Y"))

# ---------------------------------------------------------------------------
# Mock-mode settings
# ---------------------------------------------------------------------------
MOCK_RESULT_PNG = Path(os.environ.get("BINDGUI_MOCK_PNG", REPO_DIR / "iptm_scores.png"))
MOCK_TARGET_PDB = Path(os.environ.get("BINDGUI_MOCK_PDB", REPO_DIR / "example" / "PDL1.pdb"))
# Seconds each simulated stage takes (fold, design, profile).
MOCK_STAGE_SEC = int(os.environ.get("BINDGUI_MOCK_STAGE_SEC", "4"))

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
# MAMBA_ROOT above must be CLUSTER paths (set them via env on the AWS host).
# ---------------------------------------------------------------------------
SSH_HOST = os.environ.get("BINDGUI_SSH_HOST", "")
SSH_PORT = int(os.environ.get("BINDGUI_SSH_PORT", "22"))
SSH_USER = os.environ.get("BINDGUI_SSH_USER", "")
SSH_KEY = os.environ.get("BINDGUI_SSH_KEY", "")  # path to the PRIVATE key on the AWS host
SSH_KEY_PASSPHRASE = os.environ.get("BINDGUI_SSH_KEY_PASSPHRASE", "") or None
# Path to a known_hosts file for host-key verification (RejectPolicy).
# If blank, Paramiko loads the system default (~/.ssh/known_hosts).
# Populate once with: ssh-keyscan <SSH_HOST> >> <file>
SSH_KNOWN_HOSTS_FILE = os.environ.get("BINDGUI_SSH_KNOWN_HOSTS_FILE", "")
# Per-job scratch root ON THE CLUSTER (job subdirs + uploaded pipeline live here).
REMOTE_DIR = os.environ.get(
    "BINDGUI_REMOTE_DIR",
    f"/storage1/fs1/rmitra/Active/minibinders/{SSH_USER or 'USER'}/bindgui",
)
REMOTE_PIPELINE_DIR = REMOTE_DIR + "/pipeline"

# ---------------------------------------------------------------------------
# Web user auth — WashU SSO / Microsoft Entra ID (OIDC), SERVER-SIDE (BFF).
# FastAPI runs the authorization-code flow with Entra and issues a session
# cookie; the browser never talks to Entra and never handles tokens.
# Disabled by default so mock/dev needs no login.
# ---------------------------------------------------------------------------
AUTH_ENABLED = os.environ.get("BINDGUI_AUTH_ENABLED", "false").lower() == "true"
# Secret for signing the session cookie (set a long random value in production).
SESSION_SECRET = os.environ.get("BINDGUI_SESSION_SECRET", "dev-insecure-change-me")
# Send the session cookie only over HTTPS (set true behind TLS in production).
COOKIE_SECURE = os.environ.get("BINDGUI_COOKIE_SECURE", "false").lower() == "true"
# Cookie SameSite policy: "lax" for same-origin (CloudFront proxies /api → ALB),
# "none" when the SPA calls the API on a different origin (needs COOKIE_SECURE=true).
COOKIE_SAMESITE = os.environ.get("BINDGUI_COOKIE_SAMESITE", "lax")

# CORS — comma-separated web origins allowed to call the API from the browser.
# Needed only when the SPA and API are on different origins (cross-origin).
# e.g. BINDGUI_CORS_ORIGINS="https://d5j3l1rgzmla.cloudfront.net"
CORS_ORIGINS = [o.strip() for o in os.environ.get("BINDGUI_CORS_ORIGINS", "").split(",") if o.strip()]

# Where to send the browser AFTER login/logout. In cross-origin mode (Option B)
# the OIDC flow runs on the API origin, so this must point back at the SPA
# (e.g. the CloudFront URL). Blank → "/" (correct for same-origin / Option A).
WEB_APP_URL = os.environ.get("BINDGUI_WEB_APP_URL", "").rstrip("/")

# ---------------------------------------------------------------------------
# Shared results library — opt-in public store of binder + selectivity results.
# Postgres (RDS) in production; a local SQLite file for dev when DB_HOST is unset.
# (DB_HOST tolerates a trailing slash, which RDS console output sometimes adds.)
#
# Settings come from backend/config.json (gitignored, holds RDS credentials for
# local use) with environment variables as a fallback. Per key the precedence is
# config.json value (if present and non-empty) > env var > default. The deployed
# container ships no config.json, so it keeps using its env vars unchanged.
# ---------------------------------------------------------------------------
_DB_CONFIG_PATH = BASE_DIR / "config.json"


def _load_db_config() -> dict:
    if _DB_CONFIG_PATH.exists():
        try:
            return json.loads(_DB_CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError) as e:  # malformed file → fall back to env
            print(f"[config] ignoring unreadable {_DB_CONFIG_PATH.name}: {e}")
    return {}


_DB_CFG = _load_db_config()


def _db_setting(key: str, default: str = "") -> str:
    """config.json value if set, else the same-named env var, else default."""
    val = _DB_CFG.get(key)
    if val is None or val == "":
        val = os.environ.get(key, default)
    return val


DB_HOST = str(_db_setting("DB_HOST")).rstrip("/")
DB_PORT = int(_db_setting("DB_PORT", "5432"))
DB_USER = _db_setting("DB_USER")
DB_PASSWORD = _db_setting("DB_PASSWORD")
DB_NAME = _db_setting("DB_NAME")
RESULTS_SQLITE = Path(os.environ.get("BINDGUI_RESULTS_SQLITE", DATA_DIR / "results.sqlite"))

ENTRA_TENANT_ID = os.environ.get("BINDGUI_ENTRA_TENANT_ID", "")
# A single CONFIDENTIAL web-app registration (client id + secret + redirect URI).
ENTRA_CLIENT_ID = os.environ.get("BINDGUI_ENTRA_CLIENT_ID", "")
ENTRA_CLIENT_SECRET = os.environ.get("BINDGUI_ENTRA_CLIENT_SECRET", "")
# Full callback URL registered in Entra, e.g. https://app.example.edu/api/auth/callback
# If blank, it is derived from the incoming request.
AUTH_REDIRECT_URI = os.environ.get("BINDGUI_AUTH_REDIRECT_URI", "")
AUTH_SCOPES = os.environ.get("BINDGUI_AUTH_SCOPES", "openid profile email")
AUTHORITY = f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}"

DATA_DIR.mkdir(parents=True, exist_ok=True)
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
