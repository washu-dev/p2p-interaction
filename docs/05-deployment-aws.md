# 05 — Deploying on AWS

Goal: host the React SPA + FastAPI on AWS, reachable by WashU users, talking to
the RIS cluster over SSH.

## Minimal viable deployment (single EC2)

```
        Internet (WashU users)
              │ HTTPS
              ▼
   ┌───────────────────────────┐
   │ EC2 instance              │
   │  nginx/caddy (TLS) :443   │  → serves frontend/ static files
   │     └─► uvicorn :8000     │     and reverse-proxies /api/*
   │  FastAPI (BINDGUI_BACKEND=ssh)
   │  /etc/bindgui/id_bindgui  │  (private key, chmod 600)
   └─────────────┬─────────────┘
                 │ SSH:22 (Elastic IP whitelisted by RIS)
                 ▼
        RIS login node → SLURM
```

### Steps
1. **Launch EC2** (small is fine — it only orchestrates; no GPU). Attach an
   **Elastic IP** so RIS can whitelist a stable egress IP.
2. **Install**: Python 3.10+, then `pip install -r backend/requirements.txt`
   (pulls in `paramiko` and `PyJWT[crypto]`).
3. **Place the SSH private key** at `/etc/bindgui/id_bindgui` (`chmod 600`);
   authorize its public key on the cluster (see 02). Better: pull it from AWS
   Secrets Manager at boot.
4. **Set env vars** (systemd unit `EnvironmentFile=`): all `BINDGUI_*` from
   [01](01-connectivity.md) + [02](02-authentication.md), with
   `BINDGUI_BACKEND=ssh` and `BINDGUI_AUTH_ENABLED=true`.
5. **Run uvicorn** behind nginx/caddy for TLS:
   ```bash
   python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000
   ```
   Terminate HTTPS at nginx/caddy and reverse-proxy to `:8000`. Use a real
   certificate (ACM/Let's Encrypt) and a DNS name registered as the Entra SPA
   redirect URI.
6. **Persistence**: `data/` holds SQLite + the local job mirror. Put it on an
   EBS volume (or back up) so run history/cache survive restarts.

### Networking
- Inbound: 443 from WashU (or campus-only via VPN).
- Outbound: 22 → RIS login node; 443 → `login.microsoftonline.com` (Entra) and
  the MSAL CDN (or vendor MSAL locally).
- See [01-connectivity.md](01-connectivity.md) for the RIS-side firewall/VPN ask.

## Run it as a service (systemd sketch)

```ini
# /etc/systemd/system/bindgui.service
[Service]
WorkingDirectory=/opt/bindcraft-gui
EnvironmentFile=/etc/bindgui/env
ExecStart=/opt/bindcraft-gui/.venv/bin/python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000
Restart=always
User=bindgui
[Install]
WantedBy=multi-user.target
```

## Hardening checklist
- [ ] TLS everywhere; no plaintext.
- [ ] SSH key in Secrets Manager, least-privilege IAM.
- [ ] `BINDGUI_AUTH_ENABLED=true` in production (never expose unauthenticated).
- [ ] Restrict inbound to campus/VPN if possible.
- [ ] Per-user job ownership in the DB (currently one shared list — see TODO).
- [ ] Resource caps / quotas so one user can't flood SLURM.
