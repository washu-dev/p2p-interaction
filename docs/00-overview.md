# 00 — Architecture overview (from the whiteboard design)

This documents the target architecture sketched on the two whiteboards and how
the current code maps to it. Read the numbered docs in order:

- [01-connectivity.md](01-connectivity.md) — AWS ↔ cluster networking + SSH
- [02-authentication.md](02-authentication.md) — cluster auth (RSA key) + web SSO (Entra)
- [03-backend-ssh-runner.md](03-backend-ssh-runner.md) — the Paramiko remote runner
- [04-frontend-sso.md](04-frontend-sso.md) — React/MSAL SPA
- [05-deployment-aws.md](05-deployment-aws.md) — hosting on AWS
- [TODO.md](TODO.md) — consolidated checklist

## The two main ideas

**1. Move the web app off the login node and onto AWS; reach the cluster over SSH.**
Previously the FastAPI server ran *on* the login node and called `sbatch`
locally. The new design hosts the React SPA + FastAPI on an **AWS server**, and
the backend drives the **RIS login node remotely via Paramiko (SSH)**, which in
turn talks to **SLURM → compute2 / storage1**. AWS↔cluster traffic crosses a
firewall, opened either by a **firewall exception** or by **extending the WashU
VPN to AWS** (Security Group).

**2. Two independent authentication layers.**
- **Machine → cluster:** an **RSA key pair**. The AWS host holds the *private*
  key; the login node trusts the matching *public* key. Paramiko connects with
  it (`ssh -i private`) — no user passwords involved.
- **Person → web app:** **WashU SSO via Microsoft Entra ID (OIDC), server-side
  (BFF).** The browser never talks to Entra. **FastAPI** runs the
  authorization-code flow and issues a **session cookie**; the React SPA just
  calls the API with that cookie.

## Target topology

```
   React SPA ──REST(+session cookie)──►  FastAPI  ──login(OIDC code flow)──► WashU SSO (Entra)
                                            │                                  (server-side only)
                                            │ Paramiko (SSH, RSA key)      (SPA + API on AWS)
                          ── firewall / VPN ─┼──────────────────────────────
                                            ▼
                            RIS login node ──► SLURM ──► compute2 / storage1
                                            ▲
                         per-job scratch dir (uploads, sbatch, logs, result.png)
```

## How the code maps to it

| Whiteboard element            | Where it lives now                              | Status |
|-------------------------------|-------------------------------------------------|--------|
| FastAPI API                   | `backend/main.py`                               | done   |
| Paramiko SSH to login node    | `backend/sshconn.py` + `RemoteSlurmRunner` in `backend/runner.py` (`BINDGUI_BACKEND=ssh`) | done (needs cluster test) |
| RSA-key cluster auth          | `BINDGUI_SSH_KEY` etc. in `backend/config.py`   | done (needs key) |
| WashU SSO / Entra (server-side, BFF) | `backend/auth.py` (code flow + session), `/api/auth/{login,callback,logout}`, `/api/me` | done (needs app reg) |
| React SPA (cookie auth)       | `web/` (Vite + TS); FastAPI serves `web/dist`   | done   |
| VPN / firewall exception      | infra task (RIS + AWS)                          | **to do** (see 01) |
| AWS hosting                   | infra task                                      | **to do** (see 05) |

## Three runtime modes (one switch: `BINDGUI_BACKEND`)

| Mode    | Where backend runs | How it reaches SLURM | Use for                |
|---------|--------------------|----------------------|------------------------|
| `mock`  | anywhere           | simulated            | UI dev on a laptop     |
| `slurm` | on the login node  | local `sbatch`       | quick on-cluster test  |
| `ssh`   | AWS (off-cluster)  | Paramiko → `sbatch`  | **the target design**  |

Auth is orthogonal: `BINDGUI_AUTH_ENABLED=true` turns on Entra verification in
any mode (default off so dev needs no login).
