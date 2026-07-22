"""Bearer-token auth for the SPA + FastAPI backend.

The React SPA uses MSAL.js to sign the user in and acquire an access token.
Every API request carries:

    Authorization: Bearer <access_token>

Enforcement is DENY-BY-DEFAULT via the `enforce_auth` global dependency (wired in
main.py): every route requires a valid JWT except the allowlist in
authpolicy.PUBLIC_API_PATHS (currently just /api/health) and non-API/static
paths. `require_user` then hands the validated identity to a handler that needs
it. The JWT signature is validated via Microsoft's JWKS endpoint, with
audience / issuer / expiry checks.

No client secret, no session cookies, no server-side OIDC flow. Disabled by
default (BINDGUI_AUTH_ENABLED=false) so mock/dev needs no login.
"""
from __future__ import annotations

from fastapi import HTTPException, Request

import authpolicy
import config

# Anonymous identity used when auth is disabled (dev/mock).
_DEV_USER = {"sub": "dev", "name": "Local Dev", "preferred_username": "dev@local"}


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
        # Token is minted for our OWN API (Entra "Expose an API" -> access_as_user).
        # aud is the client-id GUID for v2 tokens or api://<client-id> for v1 —
        # accept both so this works regardless of requestedAccessTokenVersion.
        audience=[config.ENTRA_CLIENT_ID, f"api://{config.ENTRA_CLIENT_ID}"],
        options={"verify_exp": True},
    )
    # Issuer differs by token version (v2: .../v2.0, v1: sts.windows.net/<tenant>/).
    # PyJWT takes only a single issuer, so validate against both manually.
    valid_issuers = {
        f"{config.AUTHORITY}/v2.0",
        f"https://sts.windows.net/{config.ENTRA_TENANT_ID}/",
    }
    if claims.get("iss") not in valid_issuers:
        raise jwt.InvalidIssuerError(f"unexpected issuer: {claims.get('iss')}")
    return claims


def _user_from_claims(claims: dict) -> dict:
    return {
        "sub": claims.get("sub"),
        "name": claims.get("name"),
        "preferred_username": claims.get("preferred_username") or claims.get("upn") or claims.get("email"),
    }


def authenticate(request: Request) -> dict:
    """Validate the Bearer token; return the user identity or raise 401."""
    token = _get_bearer(request)
    if not token:
        raise HTTPException(401, "missing Bearer token")
    try:
        claims = _validate_jwt(token)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(401, f"invalid token: {e}") from e
    return _user_from_claims(claims)


def enforce_auth(request: Request) -> None:
    """Global dependency (wired in main.py): deny-by-default auth for every route.

    No-op when auth is disabled. Otherwise allows the public allowlist / static
    paths (authpolicy.is_public) and requires a valid JWT for everything else,
    caching the identity on request.state so require_user need not re-validate.
    """
    if not config.AUTH_ENABLED:
        return
    if authpolicy.is_public(request.url.path, request.method):
        return
    request.state.user = authenticate(request)  # raises 401 on missing/invalid


def require_user(request: Request) -> dict:
    """FastAPI dependency — returns the authenticated user for handlers that use
    the identity. Reuses the token already validated by enforce_auth."""
    if not config.AUTH_ENABLED:
        return _DEV_USER
    user = getattr(request.state, "user", None)
    if user is not None:
        return user
    return authenticate(request)  # fallback (e.g. a public route that still wants the user)
