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

## H. SSH runner security hardening (parking lot) — from the 2026-07 review
Prioritized; #1 is code-only and highest-leverage.
- ⬜ **Dev** 🔴 **Validate user input before it reaches the rendered sbatch** (RCE-over-SSH vector). In `create_job` (`main.py`): enforce `filters_preset`/`advanced_preset` ∈ `list_filter_presets()`/`list_advanced_presets()` (allowlist exists, not enforced — `main.py:288-289`); `slurm_account` regex `^[A-Za-z0-9._-]{1,64}$` (`main.py:297`, lands in `#SBATCH -A` — `bindcraft.sbatch.tmpl:4`); constrain `targets`/`binder_name`/`chains` to `^[A-Za-z0-9._:-]+$`.
- ⬜ **You/RIS** 🟠 **Restrict the key on the cluster side**: `authorized_keys` with `from="<AWS-EIP>",restrict,command="<wrapper>"` allowing only `sbatch/squeue/sacct/scancel` + SFTP to the job dir; run under a dedicated `svc-bindgui` account with quotas + fixed SLURM account. Prefer short-TTL SSH certificates over a static key.
- ⬜ **Dev** 🟠 **Passphrase + key handling**: fetch `ssh/KEY_PASSPHRASE` from Secrets Manager (today `config.py:85` reads a plaintext env var; `fetch_secrets.py` never materializes it). Load the private key **in memory** (`paramiko …Key.from_private_key(StringIO(pem))`, pass `pkey=`) instead of writing it to disk. Add key/cert rotation.
- ⬜ **You** 🟡 **Network**: move off the public port-22 exception to site-to-site/Client VPN; lock SG egress to `login-node-IP:22`; pin one stable login node.
- ⬜ **Dev** 🟡 **Host-key pinning**: pin RIS's real host-key fingerprint (obtained out-of-band) instead of `ssh-keyscan` TOFU; fail loudly at startup if neither `BINDGUI_SSH_KNOWN_HOSTS_FILE` nor seeded data is present (`sshconn.py:49-54`).
- ⬜ **Dev** 🟡 **Paramiko robustness**: `transport.set_keepalive(30)`, explicit `auth_timeout`/`banner_timeout`, optional `disable_algorithms` for weak KEX/ciphers; consider a small connection pool (single shared conn + global lock today — `sshconn.py:35`).
- ⬜ **Dev** ⬜ **Minor**: assert `scheduler_id.isdigit()` before interpolating into `squeue/scancel` (`runner.py:293-294,323`).

## Suggested order
1. **A + B** → raw `ssh` from AWS works, then `ssh` mode submits a real job (D test).
2. **F (minimal)** → reachable over HTTPS.
3. **C** → turn on Entra SSO.
4. **D verify + G** → harden for real users.
5. **E (React)** → optional polish.
