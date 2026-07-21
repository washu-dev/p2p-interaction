"""Regression tests for the layered config loader + fail-fast validation.

Config resolves at import time, so each scenario runs in a fresh subprocess with
its own environment. Dependency-free: run directly (`python3 tests/test_config.py`)
or under pytest. Exercises the loader only (no FastAPI/DB), matching the intended
local test scope.
"""
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

_SNIPPET = "import config; print('PROBLEMS:', config.validate())"


def _run(env_overrides: dict) -> str:
    import os
    env = {**os.environ, **env_overrides}
    out = subprocess.run(
        [sys.executable, "-c", _SNIPPET],
        cwd=str(BACKEND), env=env, capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_dev_has_no_problems():
    # dev defaults (mock backend, auth off, SQLite) are legitimate.
    assert "PROBLEMS: []" in _run({"BINDGUI_ENV": "dev"})


def test_prod_flags_mock_and_auth():
    out = _run({"BINDGUI_ENV": "prod"})
    assert "BINDGUI_BACKEND=mock in prod" in out
    assert "BINDGUI_AUTH_ENABLED must be true in prod" in out


def test_prod_ssh_requires_credentials():
    out = _run({"BINDGUI_ENV": "prod", "BINDGUI_BACKEND": "ssh"})
    for key in ("BINDGUI_SSH_HOST", "BINDGUI_SSH_USER", "BINDGUI_SSH_KEY", "BINDGUI_SSH_KNOWN_HOSTS_FILE"):
        assert f"{key} is required" in out


def test_happy_prod_is_clean():
    out = _run({
        "BINDGUI_ENV": "prod", "BINDGUI_BACKEND": "ssh", "BINDGUI_AUTH_ENABLED": "true",
        "BINDGUI_SSH_HOST": "h", "BINDGUI_SSH_USER": "u",
        "BINDGUI_SSH_KEY": "/k", "BINDGUI_SSH_KNOWN_HOSTS_FILE": "/kh",
    })
    assert "PROBLEMS: []" in out


def test_invalid_backend_rejected():
    assert "is not one of" in _run({"BINDGUI_ENV": "dev", "BINDGUI_BACKEND": "banana"})


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok - {t.__name__}")
    print(f"\n{len(tests)} passed")
