# 02 — Authentication (two layers)

The whiteboard splits auth into **machine→cluster** (RSA key) and
**person→app** (WashU SSO / Entra). They are independent; configure each.

---

## Layer A — Cluster access via RSA key pair (Paramiko)

The AWS backend authenticates to the login node with a key pair, not a password.

### Steps
1. **Generate a dedicated key pair** on the AWS host (no passphrase, or set one
   and pass it via `BINDGUI_SSH_KEY_PASSPHRASE`):
   ```bash
   ssh-keygen -t ed25519 -f /etc/bindgui/id_bindgui -C "bindgui-aws"
   # (RSA also fine: ssh-keygen -t rsa -b 4096 ...)
   ```
2. **Authorize the public key** on the cluster account:
   ```bash
   ssh-copy-id -i /etc/bindgui/id_bindgui.pub d.mingyue@c2-login-001.ris.wustl.edu
   # or append id_bindgui.pub to ~/.ssh/authorized_keys on the login node
   ```
3. **Point the backend at the private key**:
   ```bash
   export BINDGUI_SSH_KEY=/etc/bindgui/id_bindgui
   # export BINDGUI_SSH_KEY_PASSPHRASE=...   # only if the key has one
   ```
4. Lock it down: `chmod 600 /etc/bindgui/id_bindgui`; restrict who can read it
   on the AWS host. Consider AWS Secrets Manager for the key material.

### Where it's implemented
- `backend/sshconn.py` — `SSHManager` opens one auto-reconnecting connection
  using `key_filename=BINDGUI_SSH_KEY`, runs commands, and does SFTP.
- `RemoteSlurmRunner` (`backend/runner.py`) uses it to upload job files, submit
  the sbatch chain, poll `squeue`/`sacct`, and pull back logs + `result.png`.

### Security notes
- This key acts **as your cluster user** — anyone who can reach the running app
  can submit jobs as you. That's exactly why Layer B (web SSO) matters.
- Prefer a key that is *only* used by the service; rotate it periodically.

---

## Layer B — Web user auth via WashU SSO / Entra (SERVER-SIDE, BFF)

So that only authorized WashU users can drive the app. **The browser never talks
to Entra and never holds tokens** — FastAPI runs the OIDC authorization-code flow
itself and issues a signed **session cookie** (Backend-for-Frontend pattern).

### App registration (one CONFIDENTIAL web app — ask your WashU Entra admin)
- Platform = **Web** (not SPA).
- **Redirect URI** = `https://<your-app-origin>/api/auth/callback`.
- Create a **client secret**.
- Note the **client ID**, **client secret**, and **tenant ID**.

(One app reg only — no separate SPA registration, since the SPA never
authenticates directly.)

### Backend config (AWS host)
```bash
export BINDGUI_AUTH_ENABLED=true
export BINDGUI_SESSION_SECRET=$(openssl rand -hex 32)   # signs the session cookie
export BINDGUI_COOKIE_SECURE=true                       # cookie only over HTTPS
export BINDGUI_ENTRA_TENANT_ID=<washu-tenant-guid>
export BINDGUI_ENTRA_CLIENT_ID=<web-app-client-id>
export BINDGUI_ENTRA_CLIENT_SECRET=<web-app-client-secret>
export BINDGUI_AUTH_REDIRECT_URI=https://<your-app-origin>/api/auth/callback
```

### Where it's implemented
- `backend/auth.py` — `login` (→ Entra authorize), `callback` (exchange code,
  validate `id_token` via JWKS/issuer/audience, store user in the session),
  `logout`, and `require_user` (reads the session). Disabled →
  returns a local "dev" user so mock/dev needs no login.
- `backend/main.py` — `SessionMiddleware` (signed cookie) + the `/api/auth/*`
  routes; all `/api/jobs*` routes require a session.
- `web/src/App.tsx` / `api.ts` — calls the API with the cookie
  (`credentials: same-origin`); on `401` it redirects the browser to
  `/api/auth/login`. No MSAL, no token handling in the browser.

### Flow
```
Browser → GET /api/auth/login → 302 → Entra login
Entra → 302 → GET /api/auth/callback (code) → FastAPI exchanges code, sets session cookie → 302 → /
Browser → GET /api/jobs (cookie) → FastAPI checks session → 200
```

### Verify
```bash
# auth on, no session -> 401
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/jobs        # 401
# login redirects to Entra
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" http://localhost:8000/api/auth/login
```
