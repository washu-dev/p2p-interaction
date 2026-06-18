# 03 — Backend SSH runner (Paramiko)

How the off-cluster backend drives the login node. Implemented by
`RemoteSlurmRunner` in `backend/runner.py`, using `backend/sshconn.py`.

## What changed vs. the on-login-node design

| Before (`slurm` mode)                    | Now (`ssh` mode)                                  |
|------------------------------------------|---------------------------------------------------|
| `sbatch`/`squeue` as local subprocesses  | same commands run **over SSH** on the login node  |
| job files on the local disk              | job files **SFTP-uploaded** to a cluster scratch dir |
| result.png served from local disk        | result.png **pulled back** via SFTP, then served  |

Both modes share the same stage templates and `render_stage()`; only the path
map and the execution channel differ.

## Per-job lifecycle in `ssh` mode

1. `main.py` writes the job's inputs to the **local** mirror
   `data/jobs/<id>/` (`target.fasta`/`target.pdb`, `settings_target.json`,
   `targets.txt`).
2. `RemoteSlurmRunner.submit()`:
   - `mkdir -p` the **remote** job dir `$BINDGUI_REMOTE_DIR/jobs/<id>`.
   - uploads the pipeline scripts once to `$BINDGUI_REMOTE_DIR/pipeline`
     (idempotent — skipped if already there).
   - SFTP-uploads this job's input files.
   - renders each stage's sbatch with **remote** paths, uploads it, and submits
     with `sbatch --parsable [--dependency=afterok:<prev>]`.
3. `poll()` runs `squeue`/`sacct` over SSH per stage, then `_sync_back()` pulls
   `*.log` (always) and `result.png` (when `profile` completes) to the local
   mirror so the API can serve them unchanged.
4. `cancel()` issues `scancel` over SSH.

## Remote layout

```
$BINDGUI_REMOTE_DIR/
├── pipeline/                # uploaded once: pdb2fasta.py, ipTM2graph.py, select_top_binder.py
└── jobs/<id>/
    ├── target.fasta|pdb     settings_target.json     targets.txt
    ├── fold.sbatch  design.sbatch  profile.sbatch
    ├── fold.log     design.log     profile.log
    ├── target.pdb → top_binder.pdb → result.png
    └── complex/ , bindcraft_out/ , fold_out/   (stage working dirs)
```

## Config

See [01-connectivity.md](01-connectivity.md). Key points:
- In `ssh` mode, `BINDGUI_BINDCRAFT_DIR`, `BINDGUI_TARGET_FASTA_DIR`,
  `BINDGUI_COLABFOLD_BIN`, `BINDGUI_MAMBA_ROOT` are **cluster** paths (they go
  verbatim into the rendered sbatch that runs on the cluster).
- `BINDGUI_REMOTE_DIR` is the cluster scratch root (large/fast storage, e.g.
  under `storage1`).

## Connectivity self-check (recommended addition)

There is no `/api/selftest` yet — see [TODO.md](TODO.md). For now, validate
manually from the AWS host:

```bash
ssh -i $BINDGUI_SSH_KEY $BINDGUI_SSH_USER@$BINDGUI_SSH_HOST \
  'hostname; squeue --version; test -d '"$BINDGUI_TARGET_FASTA_DIR"' && echo fasta-dir-ok; \
   test -d '"$BINDGUI_MAMBA_ROOT"'/envs/'"$BINDGUI_MICROMAMBA_ENV"' && echo env-ok'
```

## Known limitations / cluster testing needed

- Untested against a live cluster (developed offline). Most likely tweak spots
  are the same three as the local templates: ColabFold rank-1 glob, micromamba
  activation, and `select_top_binder.py` CSV parsing.
- One shared SSH connection guarded by a lock; for many concurrent users a small
  connection pool would be better (see TODO).
- Polling is pull-based on each `/api/jobs` request; consider a background
  poller for many jobs.
