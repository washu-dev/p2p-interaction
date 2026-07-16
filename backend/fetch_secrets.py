"""Populate secrets/config from AWS Secrets Manager at container startup.

Run by entrypoint.sh before uvicorn. Everything here is gated on
BINDGUI_FETCH_SECRETS=true (local/dev has no AWS access), and each item is
skipped when its own config is absent and never clobbers a file that already
exists (a hand-written local override wins). Fetches:

  1. DB_PASSWORD -> backend/config.json  (config.py's _db_setting() prefers it).
  2. SSH private key -> the file at BINDGUI_SSH_KEY (chmod 600), so the Paramiko
     ssh runner can authenticate to the RIS login node. Enabled by setting
     BINDGUI_SSH_KEY_SECRET to the Secrets Manager secret holding the PEM key.
  3. known_hosts -> the file at BINDGUI_SSH_KNOWN_HOSTS_FILE, written from the
     plain env var BINDGUI_SSH_KNOWN_HOSTS_DATA (host keys aren't secret, so this
     is an ordinary task-definition env var, not a Secrets Manager secret).

The DB connection and the job runner (mock/slurm/ssh) are independent concerns,
so a deployment can mix them (real Postgres + mock jobs, or vice versa).
"""
import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

DB_PASSWORD_SECRET_NAME = os.environ.get("BINDGUI_DB_PASSWORD_SECRET", "MINIBINDERS-DBPASSWORD")
SSH_KEY_SECRET_NAME = os.environ.get("BINDGUI_SSH_KEY_SECRET", "")
AWS_REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"


def _fetch_db_password(client) -> int:
    if CONFIG_PATH.exists():
        print(f"[fetch_secrets] {CONFIG_PATH.name} already present — leaving it alone")
        return 0
    try:
        response = client.get_secret_value(SecretId=DB_PASSWORD_SECRET_NAME)
    except Exception as e:  # noqa: BLE001 — surface any boto/network failure as a fatal rc
        print(f"[fetch_secrets] FATAL: could not fetch secret '{DB_PASSWORD_SECRET_NAME}': {e}", file=sys.stderr)
        return 1
    db_password = response.get("SecretString")
    if not db_password:
        print(f"[fetch_secrets] FATAL: secret '{DB_PASSWORD_SECRET_NAME}' has no SecretString", file=sys.stderr)
        return 1
    CONFIG_PATH.write_text(json.dumps({"DB_PASSWORD": db_password}))
    CONFIG_PATH.chmod(0o600)
    print(f"[fetch_secrets] wrote DB_PASSWORD into {CONFIG_PATH.name}")
    return 0


def _fetch_ssh_key(client) -> int:
    if not SSH_KEY_SECRET_NAME:
        return 0  # ssh-key delivery not configured (e.g. mock/slurm mode)
    dest = os.environ.get("BINDGUI_SSH_KEY")
    if not dest:
        print("[fetch_secrets] FATAL: BINDGUI_SSH_KEY_SECRET is set but BINDGUI_SSH_KEY "
              "(destination path) is not", file=sys.stderr)
        return 1
    path = Path(dest)
    if path.exists():
        print(f"[fetch_secrets] {dest} already present — leaving it alone")
        return 0
    try:
        response = client.get_secret_value(SecretId=SSH_KEY_SECRET_NAME)
    except Exception as e:  # noqa: BLE001
        print(f"[fetch_secrets] FATAL: could not fetch ssh-key secret '{SSH_KEY_SECRET_NAME}': {e}", file=sys.stderr)
        return 1
    key = response.get("SecretString")
    if not key:
        print(f"[fetch_secrets] FATAL: secret '{SSH_KEY_SECRET_NAME}' has no SecretString", file=sys.stderr)
        return 1
    if not key.endswith("\n"):
        key += "\n"  # OpenSSH/PEM private keys require a trailing newline
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key)
    path.chmod(0o600)
    print(f"[fetch_secrets] wrote SSH private key to {dest}")
    return 0


def _write_known_hosts() -> int:
    data = os.environ.get("BINDGUI_SSH_KNOWN_HOSTS_DATA")
    dest = os.environ.get("BINDGUI_SSH_KNOWN_HOSTS_FILE")
    if not data or not dest:
        return 0  # not configured
    path = Path(dest)
    if path.exists():
        print(f"[fetch_secrets] {dest} already present — leaving it alone")
        return 0
    if not data.endswith("\n"):
        data += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data)
    print(f"[fetch_secrets] wrote known_hosts to {dest}")
    return 0


def main() -> int:
    if os.environ.get("BINDGUI_FETCH_SECRETS", "false").lower() != "true":
        print("[fetch_secrets] BINDGUI_FETCH_SECRETS not set to true — skipping Secrets Manager fetch")
        return 0

    import boto3

    client = boto3.client("secretsmanager", region_name=AWS_REGION)

    rc = 0
    rc |= _fetch_db_password(client)
    rc |= _fetch_ssh_key(client)
    rc |= _write_known_hosts()
    return rc


if __name__ == "__main__":
    sys.exit(main())
