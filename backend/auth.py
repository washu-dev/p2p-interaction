"""Bearer-token auth for the SPA + FastAPI backend.

The React SPA uses MSAL.js to sign the user in and acquire an access token
scoped to User.Read.  Every API request carries:

    Authorization: Bearer <access_token>

FastAPI validates the JWT signature (via Microsoft's JWKS endpoint), checks
audience / issuer / expiry, and returns the user claims.

No client secret, no session cookies, no server-side OIDC flow.

Disabled by default (BINDGUI_AUTH_ENABLED=false) so mock/dev needs no login.
"""
from __future__ import annotations

import config
from fastapi import HTTPException, Request


def _get_bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


def _validate_jwt(token: str) -> dict:
    import jwt  # PyJWT

    jwks_url = f"{config.AUTHORITY}/discovery/v2.0/keys"
    client = jwt.PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=3600)
    key = client.get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        key.key,
        algorithms=["RS256"],
        # User.Read access tokens have aud = Microsoft Graph
        audience="00000003-0000-0000-c000-000000000000",
        issuer=f"{config.AUTHORITY}/v2.0",
        options={"verify_exp": True},
    )
    return claims


def require_user(request: Request) -> dict:
    """FastAPI dependency — returns the authenticated user or raises 401."""
    if not config.AUTH_ENABLED:
        return {"sub": "dev", "name": "Local Dev", "preferred_username": "dev@local"}

    token = _get_bearer(request)
    if not token:
        raise HTTPException(401, "missing Bearer token")

    try:
        claims = _validate_jwt(token)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(401, f"invalid token: {e}") from e

    return {
        "sub": claims.get("sub"),
        "name": claims.get("name"),
        "preferred_username": claims.get("preferred_username") or claims.get("upn") or claims.get("email"),
    }
