"""Tests for the deny-by-default auth policy (authpolicy.is_public).

Pure — no FastAPI import — so it runs standalone (`python3 tests/test_authpolicy.py`)
or under pytest. Includes a check that parses main.py's real routes and asserts
/api/health is the ONLY API path exempt from JWT auth.
"""
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import authpolicy  # noqa: E402


def test_health_is_public():
    assert authpolicy.is_public("/api/health", "GET")


def test_only_health_is_allowlisted():
    assert authpolicy.PUBLIC_API_PATHS == frozenset({"/api/health"})


def test_other_api_paths_require_auth():
    for path in ("/api/config", "/api/jobs", "/api/jobs/{jid}", "/api/me", "/api/library"):
        assert not authpolicy.is_public(path, "GET"), path


def test_preflight_and_static_are_public():
    assert authpolicy.is_public("/api/jobs", "OPTIONS")   # CORS preflight
    assert authpolicy.is_public("/", "GET")               # SPA shell
    assert authpolicy.is_public("/assets/app.js", "GET")  # SPA assets
    assert authpolicy.is_public("/docs", "GET")           # FastAPI docs (non-/api)


def test_every_api_route_in_main_except_health_requires_auth():
    """Parse main.py's route decorators; /api/health must be the only public one."""
    main_src = (BACKEND / "main.py").read_text()
    api_routes = set(re.findall(r'@app\.(?:get|post|put|delete|patch)\("(/api/[^"]*)"', main_src))
    assert "/api/health" in api_routes, "sanity: health route not found"
    public = {p for p in api_routes if authpolicy.is_public(p, "GET")}
    assert public == {"/api/health"}, f"unexpected public API routes: {public - {'/api/health'}}"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok - {t.__name__}")
    print(f"\n{len(tests)} passed")
