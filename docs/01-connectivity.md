# 01 — Connectivity (AWS ↔ RIS cluster)

The backend runs on AWS and must open an **SSH** session to the WashU RIS login
node. RIS sits behind the campus firewall, so AWS traffic has to be allowed in.

## The path

```
AWS host (FastAPI) ──SSH:22──► RIS login node (c2-login-00x.ris.wustl.edu)
                                      │
                                  SLURM → compute2 / storage1
```

## Two ways to open the firewall (whiteboard options 1 & 2)

**Option 1 — Firewall exception (simplest to start).**
Ask RIS to allow inbound SSH (port 22) to the login node from your AWS host's
**static/Elastic IP**. On AWS, the instance's **Security Group** must allow
*outbound* 22 to the login node. Pin the AWS egress IP (Elastic IP or NAT
gateway) so RIS can whitelist it.

**Option 2 — Extend the WashU VPN to AWS.**
Run the WashU/RIS VPN client (or a site-to-site VPN / AWS Client VPN) so the AWS
host is on a WashU-routable network, then SSH as if on-campus. More setup, but
avoids per-IP firewall exceptions and is the more durable answer for production.

> Recommendation: start with **Option 1** (one IP whitelisted) to validate the
> end-to-end flow, then move to **Option 2 / site-to-site VPN** for production.

## What to request from RIS / what to confirm

- [ ] Inbound SSH (22) to the login node **from the AWS Elastic IP**.
- [ ] Confirm the exact login hostname(s). Note: the public alias round-robins
      across nodes — for a long-lived backend, target a **single stable node**
      (or whatever RIS recommends) so SSH and job state stay consistent.
- [ ] Confirm that submitting SLURM jobs over a non-interactive SSH session is
      allowed (some sites restrict this).
- [ ] Outbound from AWS to `login.microsoftonline.com` (443) for Entra (see 02).

## Backend config (set on the AWS host)

```bash
export BINDGUI_BACKEND=ssh
export BINDGUI_SSH_HOST=c2-login-001.ris.wustl.edu
export BINDGUI_SSH_USER=d.mingyue
export BINDGUI_SSH_KEY=/etc/bindgui/id_rsa          # private key (see 02)
export BINDGUI_REMOTE_DIR=/storage1/fs1/rmitra/Active/minibinders/d.mingyue/bindgui
# cluster paths (used inside the rendered sbatch scripts):
export BINDGUI_BINDCRAFT_DIR=/rdcw/fs2/rmitra/Active/minibinders/d.mingyue/BindCraft
export BINDGUI_TARGET_FASTA_DIR=/storage1/fs1/rmitra/Active/minibinders/d.mingyue/kinase_sequence
export BINDGUI_COLABFOLD_BIN=/storage1/fs1/rmitra/Active/minibinders/d.mingyue/localcolabfold/.pixi/envs/default/bin
export BINDGUI_MAMBA_ROOT=/rdcw/fs2/rmitra/Active/minibinders/d.mingyue/BindCraft/Y
```

## How to verify connectivity

```bash
# from the AWS host, raw SSH must work first:
ssh -i /etc/bindgui/id_rsa d.mingyue@c2-login-001.ris.wustl.edu 'hostname; squeue --version'
```
If that succeeds, the backend's Paramiko connection will too. See
[03-backend-ssh-runner.md](03-backend-ssh-runner.md) for the app-level check.
