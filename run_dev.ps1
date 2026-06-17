# Local dev on Windows (mock scheduler — no cluster needed).
# Run from the gui/ directory:  ./run_dev.ps1
$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
& .\.venv\Scripts\Activate.ps1
pip install -q -r backend/requirements.txt

$env:BINDGUI_BACKEND = "mock"
Write-Host "BindCraft GUI (mock mode) -> http://127.0.0.1:8000"
python -m uvicorn main:app --reload --app-dir backend --host 127.0.0.1 --port 8000
