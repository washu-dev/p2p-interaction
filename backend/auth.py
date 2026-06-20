"""Server-side WashU SSO / Microsoft Entra ID auth (Backend-for-Frontend).

The browser NEVER talks to Entra directly. FastAPI runs the OIDC
authorization-code flow itself and stores the resulting user in a signed
session cookie; the React SPA just calls the API with that cookie.

  GET  /api/auth/login     -> 302 to Entra authorize
  GET  /api/auth/callback  -> exchange code, validate id_token, set session
  GET  /api/auth/logout    -> clear session, 302 to Entra logout
  require_user             -> dependency that reads the session

Disabled by default (BINDGUI_AUTH_ENABLED=false) -> every request is a local
"dev" user, so mock/dev needs no login. httpx/PyJWT are imported lazily.
"""
from __future__ import annotations

import secrets
from urllib.parse import urlencode

import config
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse


def _authorize_url():
    return f"{config.AUTHORITY}/oauth2/v2.0/authorize"


def _token_url():
    return f"{config.AUTHORITY}/oauth2/v2.0/token"


def _redirect_uri(request: Request) -> str:
    return config.AUTH_REDIRECT_URI or str(request.url_for("auth_callback"))


def auth_config() -> dict:
    """Public — the SPA only needs to know whether to show a Login button."""
    return {"enabled": config.AUTH_ENABLED, "login_url": "/api/auth/login"}


async def login(request: Request):
    if not config.AUTH_ENABLED:
        return RedirectResponse("/")
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    request.session["oauth_nonce"] = nonce
    params = {
        "client_id": config.ENTRA_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": _redirect_uri(request),
        "response_mode": "query",
        "scope": config.AUTH_SCOPES,
        "state": state,
        "nonce": nonce,
    }
    return RedirectResponse(f"{_authorize_url()}?{urlencode(params)}")


async def callback(request: Request):
    if not config.AUTH_ENABLED:
        return RedirectResponse("/")
    if request.query_params.get("error"):
        desc = request.query_params.get("error_description", request.query_params["error"])
        raise HTTPException(400, f"login error: {desc}")
    if request.query_params.get("state") != request.session.get("oauth_state"):
        raise HTTPException(400, "invalid OAuth state")
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(400, "missing authorization code")

    import httpx
    import jwt

    data = {
        "client_id": config.ENTRA_CLIENT_ID,
        "client_secret": config.ENTRA_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _redirect_uri(request),
        "scope": config.AUTH_SCOPES,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(_token_url(), data=data)
    if r.status_code != 200:
        raise HTTPException(401, f"token exchange failed: {r.text}")

    id_token = r.json().get("id_token")
    if not id_token:
        raise HTTPException(401, "no id_token returned by Entra")
    try:
        jwks = jwt.PyJWKClient(f"{config.AUTHORITY}/discovery/v2.0/keys")
        key = jwks.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            key.key,
            algorithms=["RS256"],
            audience=config.ENTRA_CLIENT_ID,
            issuer=f"{config.AUTHORITY}/v2.0",
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(401, f"invalid id_token: {e}") from e

    if claims.get("nonce") != request.session.get("oauth_nonce"):
        raise HTTPException(401, "invalid nonce")

    request.session.pop("oauth_state", None)
    request.session.pop("oauth_nonce", None)
    request.session["user"] = {
        "sub": claims.get("sub"),
        "name": claims.get("name"),
        "preferred_username": claims.get("preferred_username") or claims.get("upn") or claims.get("email"),
    }
    return RedirectResponse("/")


async def logout(request: Request):
    request.session.clear()
    if not config.AUTH_ENABLED:
        return RedirectResponse("/")
    params = {"post_logout_redirect_uri": str(request.base_url).rstrip("/")}
    return RedirectResponse(f"{config.AUTHORITY}/oauth2/v2.0/logout?{urlencode(params)}")


def require_user(request: Request) -> dict:
    """Dependency: the logged-in user (or a dev stub when auth is disabled)."""
    if not config.AUTH_ENABLED:
        return {"sub": "dev", "name": "Local Dev", "preferred_username": "dev@local"}
    user = request.session.get("user")
    if not user:
        raise HTTPException(401, "not authenticated")
    return user
