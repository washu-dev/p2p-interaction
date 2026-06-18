# BindCraft GUI

A web front-end for the full binder-design + selectivity pipeline. A user
uploads a target (`.pdb` or `.fasta`), sets BindCraft parameters in the browser,
and the backend runs the staged pipeline on the cluster, streaming per-stage
progress back and showing the final **ipTM-vs-kinase** plot. Identical re-runs
are served instantly from a result cache.

```
Browser ──login──► WashU SSO (Entra)        target architecture (see docs/)
   │ Bearer JWT
   ▼
React SPA ─REST(+token)─► FastAPI ──┐        (SPA + API hosted on AWS)
                                    │ runner:
                ┌───────────────────┼─────────────────────────────────┐
                │ mock  → simulate on a laptop (dev)                    │
                │ slurm → local sbatch (backend ON the login node)      │
                │ ssh   → Paramiko/RSA to login node (backend on AWS) ◄─┘ target
                └───────────────────┴─────────────────────────────────┘
                                    ▼
                       RIS login node → SLURM → compute2 / storage1
```

> **Architecture & setup docs:** see [`docs/`](docs/00-overview.md) —
> connectivity (VPN/firewall), authentication (RSA key + Entra SSO), the SSH
> runner, frontend SSO, AWS deployment, and the [TODO checklist](docs/TODO.md).
> The `mock`/`slurm` modes below work today; `ssh`+SSO is the target design.

## The pipeline (per job)

| Stage     | Runs when            | Script                          | Produces        |
|-----------|----------------------|---------------------------------|-----------------|
| **fold**  | a FASTA was uploaded | `pipeline/fold_target.sbatch.tmpl` (ColabFold) | `target.pdb` |
| **design**| always               | `pipeline/bindcraft.sbatch.tmpl` (BindCraft)   | `top_binder.pdb` (top-ranked, via `select_top_binder.py`) |
| **profile**| always              | `pipeline/profile.sbatch.tmpl` (`pdb2fasta.py` → ColabFold → `ipTM2graph.py`) | `result.png` |

A PDB upload skips **fold** (2 stages); a FASTA upload runs all 3. Stages are
chained with `--dependency=afterok` in SLURM mode and run in series in mock mode.

BindCraft settings entered in the GUI (binder name, chains, hotspots, length
range, # designs) are written to a per-job `settings_target.json`; the filter
and advanced presets are picked from your existing `settings_filters/` and
`settings_advanced/` directories.

## Quick start (laptop, mock mode)

No cluster needed — simulates each stage and returns the repo's sample artifacts.

```powershell
cd gui
./run_dev.ps1
```
Open http://127.0.0.1:8000 → upload `example/PDL1.pdb` (or a `.fasta`), set
params, **Run pipeline**. Watch the stage dots light up and the plot appear.
Submit the same file+settings again to see the cache prompt.

### Frontend (React) — `gui/web/`
The UI is a **React + TypeScript (Vite)** app. FastAPI serves the built bundle
(`web/dist`) when present, else the buildless `frontend/index.html`.

```bash
cd gui/web && npm install && npm run build   # one-time / on change → web/dist
# hot-reload dev (proxies /api → :8000):  npm run dev   → http://localhost:5173
```
See [docs/04-frontend-sso.md](docs/04-frontend-sso.md).

## Cluster (real SLURM)

On the **login node**:

```bash
cd gui
./run_cluster.sh        # sets BINDGUI_BACKEND=slurm
```
Then users browse to `http://<login-node>:8000` (or SSH-tunnel:
`ssh -L 8000:localhost:8000 you@login-node`).

Point the env vars in `run_cluster.sh` / `backend/config.py` at your paths:

| Env var                     | What it is                                   |
|-----------------------------|----------------------------------------------|
| `BINDGUI_BINDCRAFT_DIR`     | BindCraft checkout (has bindcraft.py + settings dirs) |
| `BINDGUI_TARGET_FASTA_DIR`  | dir of `<kinase>.fasta` for the selectivity panel |
| `BINDGUI_COLABFOLD_BIN`     | dir containing `colabfold_batch`             |
| `BINDGUI_MICROMAMBA_ENV`    | micromamba env name for BindCraft            |
| `BINDGUI_SLURM_ACCOUNT` / `_PARTITION` | SLURM account / partition         |

## API

| Method | Path                        | Purpose                                   |
|--------|-----------------------------|-------------------------------------------|
| GET    | `/api/config`               | mode + filter/advanced presets + kinases  |
| POST   | `/api/jobs`                 | multipart: target file + JSON `payload`; returns `cache_hit` if dup |
| GET    | `/api/jobs`                 | list runs (live status + stages)          |
| GET    | `/api/jobs/{id}`            | one run                                   |
| GET    | `/api/jobs/{id}/result.png` | the ipTM-vs-kinase plot                   |
| GET    | `/api/jobs/{id}/logs`       | per-stage logs                            |
| POST   | `/api/jobs/{id}/cancel`     | cancel remaining stages                   |

## Caching / dedup

Each run is keyed by `sha256(uploaded_file_bytes + settings)`. On submit, an
identical **COMPLETED** run is offered back (`cache_hit`); the user picks *Use
existing result* or *Run again* (`force: true`).

## Cluster bits to verify (can't be tested off-cluster)

These templates encode reasonable defaults but depend on your environment:
- **fold**: which ColabFold output is the rank-1 model (`*rank_001*.pdb` glob).
- **design**: micromamba activation + `CONDA_BASE` path in `bindcraft.sbatch.tmpl`.
- **design**: how the top binder is chosen — `select_top_binder.py` reads
  `final_design_stats.csv` (best-first) and falls back to newest in `Accepted/`.
  Confirm your column name / output layout.

## Next steps (not yet wired)

- PDB chain selection UI (currently fixed by the `chains` field).
- Auth + per-user run history (one shared list today).
- Parallelize the profile fold as a SLURM array + dependent plot job.
- Live log streaming (WebSocket) instead of on-demand fetch.
