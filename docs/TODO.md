# TODO — path to the whiteboard architecture

Status legend: ✅ done in code · 🟡 scaffolded, needs config/secrets · 🔵 infra/admin · ⬜ not started
Owner: **You** = d.mingyue · **RIS** = WashU RIS/IT · **Entra** = WashU Entra admin · **Dev** = code work

## A. Connectivity (AWS ↔ cluster) — see 01
- 🔵 **RIS**: open inbound SSH (22) to the login node from the AWS Elastic IP (Option 1), *or* set up site-to-site / extend WashU VPN to AWS (Option 2).
- 🔵 **RIS**: confirm a stable login hostname for a long-lived backend (avoid the round-robin alias).
- 🔵 **RIS**: confirm SLURM submission over non-interactive SSH is permitted.
- ⬜ **You**: allocate AWS Elastic IP; set Security Group egress 22 → login node.

## B. Cluster auth — RSA key — see 02
- ✅ **Dev**: Paramiko key-based connection (`sshconn.py`, `RemoteSlurmRunner`).
- ⬜ **You**: `ssh-keygen` a dedicated key on the AWS host.
- ⬜ **You**: authorize the public key on the cluster account (`authorized_keys`).
- ⬜ **You**: set `BINDGUI_SSH_KEY` (+ store private key in Secrets Manager).

## C. Web user auth — WashU SSO / Entra (server-side BFF) — see 02 & 04
- ✅ **Dev**: server-side OIDC code flow + session cookie (`auth.py`, `/api/auth/{login,callback,logout}`, `/api/me`, protected `/api/jobs*`). Browser never touches Entra.
- ✅ **Dev**: React app uses the cookie; `401` → `/api/auth/login`.
- 🔵 **Entra**: register **one confidential Web app** — redirect URI `https://<origin>/api/auth/callback`, create a client secret.
- ⬜ **You**: set `BINDGUI_AUTH_ENABLED=true`, `BINDGUI_SESSION_SECRET`, `BINDGUI_COOKIE_SECURE=true`, and `BINDGUI_ENTRA_{TENANT_ID,CLIENT_ID,CLIENT_SECRET}` + `BINDGUI_AUTH_REDIRECT_URI`.

## D. Backend remote runner — see 03
- ✅ **Dev**: `ssh` mode — upload inputs, submit chained sbatch, poll, sync back logs + result.png.
- ✅ **Dev**: single H100 per design stage; absolute `MAMBA_ROOT_PREFIX`; `set +u` around activation.
- ⬜ **You**: end-to-end test on the real cluster (the offline-developed runner is untested live).
- ⬜ **Dev**: verify the 3 cluster-specific spots — ColabFold rank-1 glob, micromamba activation, `select_top_binder.py` CSV parsing — against real outputs.
- ⬜ **Dev** (nice-to-have): `/api/selftest` endpoint (checks SSH, env root, colabfold_batch, fasta dir) for one-click validation.
- ⬜ **Dev** (scale): SSH connection pool + background poller for many concurrent jobs.

## E. Frontend — see 04
- ✅ **Dev**: React + TS (Vite) wizard in `web/`, cookie-based auth, builds to `web/dist` (FastAPI serves it).
- ✅ **Dev**: buildless `frontend/index.html` kept as a zero-toolchain fallback.
- ⬜ **You/host**: `npm ci && npm run build` in CI / on the AWS host as part of deploy.

## F. AWS deployment — see 05
- ⬜ **You**: launch EC2 + Elastic IP; install deps.
- ⬜ **You**: nginx/caddy TLS in front of uvicorn; real DNS + cert.
- ⬜ **You**: systemd service; `EnvironmentFile` with all `BINDGUI_*`.
- ⬜ **You**: put `data/` on persistent EBS (keeps run history + cache).

## G. Multi-user hardening — see 05
- ⬜ **Dev**: store the authenticated user on each job; scope the run list per user (today it's one shared list).
- ⬜ **Dev**: per-user quotas / rate limits on submissions.
- ⬜ **You**: restrict inbound to campus/VPN where possible.

## Suggested order
1. **A + B** → raw `ssh` from AWS works, then `ssh` mode submits a real job (D test).
2. **F (minimal)** → reachable over HTTPS.
3. **C** → turn on Entra SSO.
4. **D verify + G** → harden for real users.
5. **E (React)** → optional polish.
