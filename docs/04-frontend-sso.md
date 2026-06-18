# 04 — Frontend: React SPA + server-side SSO

The frontend is a **React + TypeScript (Vite)** app in `gui/web/`. It follows the
whiteboard's **React → FastAPI → SSH** topology and the BFF auth model: the
browser talks only to FastAPI (same origin), never to Entra.

## Layout
```
gui/web/
├── package.json  vite.config.ts  tsconfig.json  index.html
└── src/
    ├── main.tsx      React entry
    ├── App.tsx       the 7-step wizard (Home → … → Download)
    ├── api.ts        fetch wrapper (cookie auth, 401 → /api/auth/login) + types
    └── styles.css    the light indigo/violet theme
```

## How auth works here (no MSAL, no tokens in the browser)
- `api.ts` sends every request with `credentials: "same-origin"` so the session
  cookie rides along automatically.
- On `401` (auth enabled, no session) it sets `window.location = "/api/auth/login"`;
  FastAPI then drives the Entra login and returns the user with a session cookie.
- `App.tsx` reads `/api/auth/config` to know if login is required and `/api/me`
  for the signed-in user (shown in the sidebar with a Sign-out button →
  `/api/auth/logout`).

This keeps all OIDC + secrets server-side (see [02](02-authentication.md)).

## Develop
```bash
# terminal 1 — backend (mock is fine for UI work)
cd gui && BINDGUI_BACKEND=mock python -m uvicorn main:app --reload --app-dir backend --port 8000
# terminal 2 — Vite dev server with hot reload, proxies /api → :8000
cd gui/web && npm install && npm run dev      # http://localhost:5173
```

## Build for production
```bash
cd gui/web && npm run build      # emits gui/web/dist/
```
FastAPI auto-serves `web/dist` when it exists (see `FRONTEND_DIR` in
`backend/config.py`); otherwise it falls back to the buildless
`frontend/index.html`. So production hosting is just: build, then run uvicorn —
no separate web server needed for the static files (though nginx/caddy still
terminates TLS — see [05](05-deployment-aws.md)).

## Notes
- The legacy buildless SPA (`frontend/index.html`) is kept as a zero-toolchain
  fallback and is feature-equivalent. Prefer the React app (`web/`) going forward.
- `node_modules/` and `dist/` are git-ignored; CI/host runs `npm ci && npm run build`.
