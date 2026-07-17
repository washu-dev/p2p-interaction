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
        ┌───────▼────────┐         login (MSAL.js, in browser)
        │  CloudFront/S3 │         ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─►  WashU SSO
        │  React SPA     │                                     (Entra ID)
        └───────┬────────┘                                        ▲
                │  REST + Bearer token (Authorization)            │ token (PKCE)
        ┌───────▼───────────────────────────────────────┐         │
        │  FastAPI on ECS (behind ALB)                  │─────────┘
        │   • CORS for the CloudFront origin            │
        │   • validates MSAL bearer tokens (JWT)        │
        │   • job store: Postgres (prod) / SQLite (dev) │
        │   • Paramiko/SSH runner (RSA key)             │──► RDS Postgres
        └───────┬───────────────────────────────────────┘    (jobs + shared
                │  SSH (firewall/VPC)                          results library)
        ┌───────▼────────┐
        │ RIS login node │──► SLURM ──► compute2 / storage1
        └────────────────┘     fold → design → profile → ipTM plot
```

**Tiers**
- **Frontend** — React + TypeScript (Vite) in `web/`, deployed to **S3 + CloudFront**
  (`web-deploy.yml`). A 7-step wizard: Upload → Structure Prediction → Binder
  Design → Selectivity Screening → Visualization → Download, plus a **Shared
  Library** page. Talks only to the API via `VITE_API_BASE_URL`, sending an
  MSAL-acquired bearer token in the `Authorization` header.
- **Backend** — FastAPI in `backend/`, containerized (`Dockerfile`) and deployed
  to **ECR/ECS** (`backend-deploy.yml`). Responsibilities: serve the API, validate
  MSAL-issued bearer tokens (JWT; no server-side flow or cookie), track jobs in
  Postgres (SQLite in dev), drive the cluster, and publish consented results to
  Postgres.
- **Pipeline runners** (`runner.py`) — one of three via `BINDGUI_BACKEND`:
  `mock` (laptop), `slurm` (on the login node), `ssh` (off-cluster via Paramiko,
  the production design). Each job is a staged DAG: optional **fold** (ColabFold,
  for FASTA targets) → **design** (BindCraft + composite binder scorer) →
  **profile** (pdb2fasta → ColabFold → ipTM-vs-kinase plot).
- **Databases** — **RDS Postgres** for both job tracking + dedup cache (`db.py`)
  and the shared, opt-in results library (`resultsdb.py`); each falls back to a
  local SQLite file in dev (when `DB_HOST` is unset).
- **Auth** — two independent layers: machine→cluster via an **SSH RSA key**;
  person→app via **WashU SSO / Entra (SPA + MSAL bearer token; the backend
  validates the JWT, `auth.py`)**.

---

## What changed vs `main`

### 1. Cross-origin support (`feat/cors-option-b`)
The SPA (CloudFront) and API (ALB) are different origins, so browser calls were
blocked. Added:
- `backend/main.py` — `CORSMiddleware`, enabled when `BINDGUI_CORS_ORIGINS` is
  set, allowing the SPA origin to send the `Authorization` header.
- `backend/config.py` — `CORS_ORIGINS`.

> Note: auth later moved to **SPA + MSAL bearer tokens** (`auth.py`), so the
> session-cookie / `COOKIE_SAMESITE` / `WEB_APP_URL` machinery this branch
> originally added is gone. The cross-origin story is now just CORS + the
> `Authorization` header.

**Deploy env (Option B):** `BINDGUI_CORS_ORIGINS=https://<cloudfront>` and
`VITE_API_BASE_URL` = the API's HTTPS URL. Because auth is a bearer token,
cross-origin works with CORS alone (no cookies). Routing `/api/*` through
CloudFront (same-origin) is still worthwhile to avoid preflights.

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

## Outstanding

These are known gaps in this branch — *what* each is, *why* it matters, and
*how* to resolve it.

- **Job persistence (SQLite → RDS Postgres). ✅ DONE.**
  `db.py` now uses RDS Postgres when `DB_HOST` is set (SQLite fallback for dev),
  so job history + the dedup cache survive ECS Fargate's ephemeral storage across
  redeploys/restarts/scale events.

- **CI security gate — Paramiko host-key policy. ✅ DONE.**
  `sshconn.py` uses `RejectPolicy` and loads `known_hosts` (from
  `BINDGUI_SSH_KNOWN_HOSTS_FILE` or the system file), so host keys are verified
  (no Bandit B507). Operationally you still seed the `known_hosts` entry for the
  RIS host (`ssh-keyscan <host>`) on the deployment.

- **ALB must serve HTTPS.**
  *What:* the API is currently `http://…elb.amazonaws.com`.
  *Why it matters:* an https CloudFront page calling an http API is **blocked as
  mixed content**, and ACM won't issue a cert for the raw `*.elb.amazonaws.com`
  name. *How:* front the ALB with a **custom domain + ACM cert**, or put a
  CloudFront distribution in front of it.

- **CloudFront `/api` routing (recommended, not required for auth).**
  *What:* the SPA (CloudFront) and API (ALB) are different origins.
  *Why it matters:* auth is a **bearer token in the `Authorization` header**, so
  cross-origin works with CORS alone — there's no third-party-cookie problem.
  Routing `/api/*` through CloudFront is still worthwhile: same-origin avoids CORS
  preflights and lets CloudFront terminate TLS in front of the ALB.
  *How:* add the ALB as a second CloudFront origin and route `/api/*` to it.

- **Entra app registration + enable auth.**
  *What:* `AUTH_ENABLED` is off; no Entra app exists yet.
  *Why it matters:* without it the API is unauthenticated. *How:* register a
  **public SPA** (PKCE, redirect = the SPA URL, **no client secret**), wire its
  client id/tenant into the SPA's MSAL config and `BINDGUI_ENTRA_TENANT_ID` /
  `BINDGUI_ENTRA_CLIENT_ID`, then flip `AUTH_ENABLED=true`. (Hardening note in
  `auth.py`: the backend currently validates the Graph `User.Read` audience; for
  a stricter setup, expose your own API scope and validate that audience.)

- **Secrets handling.**
  *What:* DB password, Entra secret, and the SSH private key are sensitive.
  *Why it matters:* they must never be in the image or repo. *How:* deliver them
  via **ECS task secrets / AWS Secrets Manager**; and **rotate the RDS password**
  (it was shared in cleartext).

- **Repo hygiene.**
  *What:* `.venv/` and `backend/__pycache__/` are committed.
  *Why it matters:* they bloat the repo and make every diff noisy (the real
  change gets buried). *How:* `git rm -r --cached .venv backend/__pycache__` and
  rely on `.gitignore`.

---

## TODOs — whole architecture 

---

## Run locally
```bash
# backend serves the built React app at one origin
python -m uvicorn main:app --app-dir backend --port 8000   # http://localhost:8000
# or hot-reload UI dev (proxies /api → :8000):
cd web && npm install && npm run dev                        # http://localhost:5173
```
