"""Which requests bypass JWT auth — a pure policy with no framework deps, so it
is unit-testable without importing FastAPI.

Deny-by-default: every request under /api/* requires a valid bearer token EXCEPT
the paths in PUBLIC_API_PATHS. Non-/api requests (the SPA static shell + its
assets, and FastAPI's /docs) and CORS preflight (OPTIONS) are always allowed.
"""

# The ONLY API paths reachable without a token. Keep this tiny and explicit —
# adding an entry here is the one deliberate way to make an endpoint public.
PUBLIC_API_PATHS = frozenset({"/api/health"})


def is_public(path: str, method: str) -> bool:
    """True if the request must NOT require a JWT."""
    if method.upper() == "OPTIONS":       # CORS preflight carries no Authorization header
        return True
    if not path.startswith("/api/"):      # SPA static files, "/", /assets/*, /docs
        return True
    return path in PUBLIC_API_PATHS
