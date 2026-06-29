# MiniBinders / p2p-interaction — integration summary

This branch (`release/full-platform`) combines three stacked feature branches on
top of `main`, in order:

1. `feat/cors-option-b` — cross-origin (CORS + Option B) support
2. `feat/results-library` — opt-in shared results library + consent checkbox
3. `feat/single-ui-docker` — one React UI built and served from Docker

---

## Overall architecture

```
            Browser (WashU user)
                │  HTTPS
        ┌───────▼────────┐         login (OIDC, server-side)
        │  CloudFront/S3 │         ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─►  WashU SSO
        │  React SPA     │                                     (Entra ID)
        └───────┬────────┘                                        ▲
                │  REST + session cookie (credentials)            │ code flow
        ┌───────▼───────────────────────────────────────┐         │
        │  FastAPI on ECS (behind ALB)                  │─────────┘
        │   • CORS for the CloudFront origin            │
        │   • server-side Entra OIDC → session cookie   │
        │   • SQLite (job tracking + dedup cache)       │
        │   • Paramiko/SSH runner (RSA key)             │──► RDS Postgres
        └───────┬───────────────────────────────────────┘    (shared results
                │  SSH (firewall/VPC)                          library)
        ┌───────▼────────┐
        │ RIS login node │──► SLURM ──► compute2 / storage1
        └────────────────┘     fold → design → profile → ipTM plot
```

**Tiers**
- **Frontend** — React + TypeScript (Vite) in `web/`, deployed to **S3 + CloudFront**
  (`web-deploy.yml`). A 7-step wizard: Upload → Structure Prediction → Binder
  Design → Selectivity Screening → Visualization → Download, plus a **Shared
  Library** page. Talks only to the API via `VITE_API_BASE_URL` with a session
  cookie (`credentials: include`).
- **Backend** — FastAPI in `backend/`, containerized (`Dockerfile`) and deployed
  to **ECR/ECS** (`backend-deploy.yml`). Responsibilities: serve the API, run the
  Entra OIDC flow server-side (the browser never talks to Entra), track jobs in
  SQLite, drive the cluster, and publish consented results to Postgres.
- **Pipeline runners** (`runner.py`) — one of three via `BINDGUI_BACKEND`:
  `mock` (laptop), `slurm` (on the login node), `ssh` (off-cluster via Paramiko,
  the production design). Each job is a staged DAG: optional **fold** (ColabFold,
  for FASTA targets) → **design** (BindCraft + composite binder scorer) →
  **profile** (pdb2fasta → ColabFold → ipTM-vs-kinase plot).
- **Databases** — SQLite for job tracking + dedup cache (per-instance); **RDS
  Postgres** for the shared, opt-in results library (`resultsdb.py`).
- **Auth** — two independent layers: machine→cluster via an **SSH RSA key**;
  person→app via **WashU SSO / Entra (server-side, session cookie)**.

---

## What changed vs `main`

### 1. Cross-origin support (`feat/cors-option-b`)
The SPA (CloudFront) and API (ALB) are different origins, so browser calls were
blocked. Added:
- `backend/main.py` — `CORSMiddleware`, enabled when `BINDGUI_CORS_ORIGINS` is
  set, with `allow_credentials` so the session cookie is sent.
- `backend/config.py` — `CORS_ORIGINS`, `COOKIE_SAMESITE`, `WEB_APP_URL`.
- `backend/auth.py` — login/logout redirect back to the SPA origin
  (`WEB_APP_URL`) instead of the API origin.

**Deploy env (Option B):** ALB must be reachable over **HTTPS** (mixed content
otherwise), `BINDGUI_CORS_ORIGINS=https://<cloudfront>`,
`BINDGUI_COOKIE_SAMESITE=none`, `BINDGUI_COOKIE_SECURE=true`,
`BINDGUI_WEB_APP_URL=https://<cloudfront>`, and `VITE_API_BASE_URL` = the API's
HTTPS URL. (Cross-site cookies are fragile under third-party-cookie blocking; a
shared parent domain for web + API is the robust fix.)

### 2. Shared results library + consent (`feat/results-library`)
Opt-in storage of binder + selectivity results, visible to signed-in users.
- `backend/resultsdb.py` (new) — portable Postgres/SQLite store:
  `public_binders` (sequence, target, composite score, design metrics) +
  `public_selectivity` (per-kinase best/avg ipTM).
- `backend/main.py` — a **consent flag** (`make_public`, recorded *after* the
  dedup key so it doesn't affect caching), publish-on-completion (idempotent),
  and `GET /api/library` (search by kinase/target/text).
- `backend/config.py` — `DB_HOST/PORT/USER/PASSWORD/NAME` (+ `RESULTS_SQLITE`
  for dev); `DB_HOST` tolerates a trailing slash.
- `backend/runner.py` — mock emits result JSON; the ssh runner syncs
  `selectivity.json` + `design_result.json` back.
- `backend/pipeline/` — `ipTM2graph.py` emits `selectivity.json`;
  `profile.sbatch.tmpl` copies it back; `select_top_binder.py` now ranks binders
  by a **weighted composite** of AF2/Rosetta/H-bond/RMSD/clash metrics and emits
  `design_result.json`.
- `backend/requirements.txt` — adds `psycopg[binary]`.
- `web/src/App.tsx` — a **consent checkbox** on the Selectivity Screening step
  and a **Shared Library** page.

### 3. Single React UI (`feat/single-ui-docker`)
The buildless `frontend/index.html` had drifted behind the React app and caused
confusion about which UI is real. Now there is one UI.
- `Dockerfile` — multi-stage: build `web/` with Node, serve `web/dist` from
  FastAPI.
- `backend/config.py` — `FRONTEND_DIR` points only at `web/dist`.
- `backend/main.py` — mount the static UI only if present (local API-only / Vite
  dev won't crash).
- Removed `frontend/index.html`.

---

## Outstanding (not in this branch)
- **Persistence:** job tracking is still SQLite on ephemeral ECS storage —
  migrate to RDS Postgres so job history/cache survive redeploys.
- **CI security gate:** `sshconn.py` uses Paramiko `AutoAddPolicy` (Bandit B507);
  wire host-key verification via `SSH_KNOWN_HOSTS_FILE` before it can pass.
- **Infra/secrets:** ALB HTTPS, CloudFront `/api` behavior or shared parent
  domain, Entra app registration, SSH key into ECS, and **rotate the RDS
  password**.
- **Repo hygiene:** `.venv/` and `backend/__pycache__/` are tracked — should be
  `git rm -r --cached`-ed.

## Run locally
```bash
# backend serves the built React app at one origin
python -m uvicorn main:app --app-dir backend --port 8000   # http://localhost:8000
# or hot-reload UI dev (proxies /api → :8000):
cd web && npm install && npm run dev                        # http://localhost:5173
```
