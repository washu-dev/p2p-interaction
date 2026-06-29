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

## Outstanding

These are known gaps in this branch — *what* each is, *why* it matters, and
*how* to resolve it.

- **Job persistence (SQLite → RDS Postgres).**
  *What:* job tracking + the dedup cache live in a SQLite file at `/app/data`.
  *Why it matters:* ECS Fargate storage is **ephemeral** — every redeploy,
  restart, or scale event wipes that file, so all run history and cached results
  vanish. *How:* port `db.py` to Postgres (the RDS instance is already there for
  the results library), keeping a SQLite fallback for local dev.

- **CI security gate — Paramiko `AutoAddPolicy`.**
  *What:* `sshconn.py` auto-accepts any host key on first connect.
  *Why it matters:* it disables SSH host-key verification (a MITM risk) and trips
  **Bandit B507**, a HIGH finding that fails the `backend-deploy.yml` security
  scan — so the image won't build/deploy. *How:* populate a `known_hosts`
  (`ssh-keyscan <host>`), point `BINDGUI_SSH_KNOWN_HOSTS_FILE` at it, and switch
  to `RejectPolicy` (the config hook already exists).

- **ALB must serve HTTPS.**
  *What:* the API is currently `http://…elb.amazonaws.com`.
  *Why it matters:* an https CloudFront page calling an http API is **blocked as
  mixed content**, and ACM won't issue a cert for the raw `*.elb.amazonaws.com`
  name. *How:* front the ALB with a **custom domain + ACM cert**, or put a
  CloudFront distribution in front of it.

- **CloudFront `/api` routing (or shared parent domain).**
  *What:* the SPA (CloudFront) and API (ALB) are different origins.
  *Why it matters:* cross-origin cookies are **third-party** and increasingly
  blocked by browsers, which would silently break login even with CORS set.
  *How:* either route `/api/*` through CloudFront to the ALB (same-origin), or
  host web + API under one parent domain (`app.` / `api.`) so the cookie is
  first-party.

- **Entra app registration + enable auth.**
  *What:* `AUTH_ENABLED` is off; no Entra app exists yet.
  *Why it matters:* without it the API is unauthenticated. *How:* register a
  confidential Web app (redirect `…/api/auth/callback`, client secret), then set
  `BINDGUI_ENTRA_*` + `SESSION_SECRET` + `COOKIE_SECURE=true` and flip
  `AUTH_ENABLED=true`.

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

Legend: ✅ done · 🟡 partial / needs config · ⬜ not started
Owners: **You** (d.mingyue) · **Lead** (AWS) · **RIS** (cluster IT) · **Entra** (WashU identity) · **Dev** (code)

### A. Connectivity (AWS ↔ RIS cluster)
- ⬜ **RIS/Lead:** open SSH from AWS — firewall exception for the AWS Elastic IP, *or* extend the WashU VPN / VPC peering.
- ⬜ **Lead:** pin a static **Elastic IP** (or NAT) so RIS can whitelist one address.
- ⬜ **RIS:** confirm SLURM submission over non-interactive SSH is allowed, and a **stable login node** to target.
- ⬜ **Dev:** if RIS requires a **bastion/jump host**, add `ProxyJump` to `sshconn.py` (currently direct-only).

### B. Cluster auth (machine → cluster)
- ✅ **Dev:** Paramiko RSA-key runner.
- ⬜ **You:** generate a dedicated key; add the **public** key to the cluster account.
- ⬜ **Lead:** deliver the **private** key to ECS via Secrets Manager.
- 🟡 **Dev/You:** enforce host-key verification (`SSH_KNOWN_HOSTS_FILE` + `RejectPolicy`) — also clears the Bandit gate.

### C. Web auth (person → app)
- ✅ **Dev:** server-side Entra OIDC + session cookie (BFF).
- ⬜ **Entra:** register the confidential Web app (redirect URI + client secret).
- ⬜ **Lead:** set `BINDGUI_ENTRA_*`, `SESSION_SECRET`, `COOKIE_SECURE`, `WEB_APP_URL`; set `AUTH_ENABLED=true`.

### D. Web ↔ API connectivity (Option B)
- ✅ **Dev:** CORS + `SameSite`/`WEB_APP_URL` knobs.
- ⬜ **Lead:** ALB on **HTTPS** (custom domain + ACM, or CloudFront in front).
- ⬜ **Lead:** set `BINDGUI_CORS_ORIGINS` + the `VITE_API_BASE_URL` repo variable.
- 🟡 **Lead:** prefer a **shared parent domain** for web + API to avoid third-party-cookie breakage.

### E. Persistence (databases)
- ⬜ **Dev:** migrate the **job store** SQLite → RDS Postgres (ephemeral-storage fix).
- ✅ **Dev:** results library is Postgres-capable (`resultsdb.py`).
- ⬜ **Lead:** provision RDS access from ECS; set `DB_*` task secrets; **rotate the password**.

### F. Pipeline correctness (cluster)
- ✅ **Dev:** composite binder scorer (verified on real `final_design_stats.csv`).
- ⬜ **You:** one real **end-to-end `ssh`-mode run** on the cluster (the Paramiko path is only mock-tested).
- ⬜ **You/Dev:** verify the ColabFold rank-1 `*.pdb` glob + the `ipTM=` grep against real output.

### G. Deployment / CI
- ✅ **Dev:** Dockerfile builds the single React UI; backend + web CI workflows exist.
- ⬜ **Dev:** pass **Bandit** (host-key fix above).
- ⬜ **Lead:** GitHub repo vars/secrets (`VITE_API_BASE_URL`, AWS creds); ECS task env; DNS + TLS.

### H. Scale / robustness
- ⬜ **Dev:** **background poller** — job status currently only advances when `/api/jobs` is hit (and that's also when ssh-mode syncs results back).
- ⬜ **Dev:** **SSH connection pool** — currently one shared connection behind a lock (serializes cluster calls).
- ⬜ **Dev:** parallelize the **profile fold** as a SLURM array (currently a serial loop).
- ⬜ **Dev:** **live log streaming** (WebSocket) instead of fetch-on-demand.

### I. Multi-user / features
- 🟡 **Dev:** **per-user job ownership** + per-user dedup cache (built in an earlier iteration; not yet folded into this repo — runs are currently one shared list).
- ⬜ **Dev:** per-user **quotas / rate limits** so one user can't flood SLURM.
- ⬜ **Dev:** **`/api/selftest`** endpoint (validate SSH/env/paths before submitting).
- ⬜ **Dev:** surface the **binder scoreboard** in the GUI (not just the winning plot).

### J. Repo hygiene
- ⬜ **You:** untrack `.venv/` and `backend/__pycache__/` (`git rm -r --cached`).

---

## Run locally
```bash
# backend serves the built React app at one origin
python -m uvicorn main:app --app-dir backend --port 8000   # http://localhost:8000
# or hot-reload UI dev (proxies /api → :8000):
cd web && npm install && npm run dev                        # http://localhost:5173
```
