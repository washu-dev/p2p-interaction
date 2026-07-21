"""Populate secrets/config from AWS Secrets Manager at container startup.

Run by entrypoint.sh before uvicorn. Everything here is gated on
BINDGUI_FETCH_SECRETS=true (local/dev has no AWS access), and each item is
skipped when its own config is absent and never clobbers a file that already
exists (a hand-written local override wins). Fetches:

  1. Value-shaped secrets -> backend/config.json (config.py's _setting() prefers
     it): the grouped MiniBinders/database/* secrets from terraform (DB_HOST,
     DB_PORT, DB_NAME, DB_USER, DB_PASSWORD; prefix BINDGUI_DB_SECRET_PREFIX,
     legacy flat MINIBINDERS-DBPASSWORD fallback for the password), plus the
     optional SSH key passphrase (BINDGUI_SSH_KEY_PASSPHRASE).
  2. SSH private key (file-shaped secret) -> the file at BINDGUI_SSH_KEY (chmod
     600), so the Paramiko ssh runner can authenticate to the RIS login node.
     Enabled by setting BINDGUI_SSH_KEY_SECRET to the Secrets Manager secret
     holding the PEM key (e.g. MiniBinders/ssh/PRIVATE_KEY).
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

# Grouped DB secrets created by terraform: each key is fetched as
# "<prefix>/<KEY>", e.g. MiniBinders/database/DB_PASSWORD.
DB_SECRET_PREFIX = os.environ.get("BINDGUI_DB_SECRET_PREFIX", "MiniBinders/database")
DB_SECRET_KEYS = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
# Legacy flat secret (pre-terraform) holding only the password; used as a
# fallback when the grouped DB_PASSWORD above can't be read.
DB_PASSWORD_SECRET_NAME = os.environ.get("BINDGUI_DB_PASSWORD_SECRET", "MINIBINDERS-DBPASSWORD")
SSH_KEY_SECRET_NAME = os.environ.get("BINDGUI_SSH_KEY_SECRET", "")
# Optional passphrase for the SSH key. Defaults to the KEY_PASSPHRASE sibling in
# the same Secrets Manager group as the key (e.g. MiniBinders/ssh/PRIVATE_KEY ->
# MiniBinders/ssh/KEY_PASSPHRASE); override with BINDGUI_SSH_PASSPHRASE_SECRET.
# Absent/empty means the key is unencrypted — that is fine, not an error.
SSH_PASSPHRASE_SECRET_NAME = os.environ.get("BINDGUI_SSH_PASSPHRASE_SECRET", "")
if not SSH_PASSPHRASE_SECRET_NAME and "/" in SSH_KEY_SECRET_NAME:
    SSH_PASSPHRASE_SECRET_NAME = SSH_KEY_SECRET_NAME.rsplit("/", 1)[0] + "/KEY_PASSPHRASE"
AWS_REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"


def _collect_db_config(client, cfg: dict) -> int:
    """Add DB connection settings from Secrets Manager into `cfg`.

    Reads each MiniBinders/database/* key created by terraform. A missing
    non-secret key (host/port/name/user) is fine — config.py falls back to its
    same-named env var. The password is required; if the grouped DB_PASSWORD is
    absent, fall back to the legacy flat secret.
    """
    for key in DB_SECRET_KEYS:
        secret_id = f"{DB_SECRET_PREFIX}/{key}"
        try:
            response = client.get_secret_value(SecretId=secret_id)
        except client.exceptions.ResourceNotFoundException:
            print(f"[fetch_secrets] {secret_id} not found — skipping (config.py uses its env var)")
            continue
        except Exception as e:  # noqa: BLE001 — surface any boto/network failure as fatal
            print(f"[fetch_secrets] FATAL: could not fetch secret '{secret_id}': {e}", file=sys.stderr)
            return 1
        value = response.get("SecretString")
        if value:
            cfg[key] = value

    if "DB_PASSWORD" not in cfg:
        # Legacy fallback: a flat secret holding only the password.
        try:
            response = client.get_secret_value(SecretId=DB_PASSWORD_SECRET_NAME)
        except Exception as e:  # noqa: BLE001
            print(f"[fetch_secrets] FATAL: no DB password in '{DB_SECRET_PREFIX}/DB_PASSWORD' "
                  f"or legacy '{DB_PASSWORD_SECRET_NAME}': {e}", file=sys.stderr)
            return 1
        legacy = response.get("SecretString")
        if legacy:
            cfg["DB_PASSWORD"] = legacy
            print(f"[fetch_secrets] used legacy secret '{DB_PASSWORD_SECRET_NAME}' for DB_PASSWORD")

    if not cfg.get("DB_PASSWORD"):
        print("[fetch_secrets] FATAL: no DB password found in Secrets Manager", file=sys.stderr)
        return 1
    return 0


def _collect_ssh_passphrase(client, cfg: dict) -> int:
    """Add the SSH key passphrase (value-shaped secret) into `cfg`, if one exists.

    Best-effort: a missing or empty passphrase secret means the key is
    unencrypted, which is valid — never fatal. config.py reads
    BINDGUI_SSH_KEY_PASSPHRASE from config.json (env fallback)."""
    if not SSH_PASSPHRASE_SECRET_NAME:
        return 0
    try:
        response = client.get_secret_value(SecretId=SSH_PASSPHRASE_SECRET_NAME)
    except client.exceptions.ResourceNotFoundException:
        print(f"[fetch_secrets] {SSH_PASSPHRASE_SECRET_NAME} not found — SSH key has no passphrase")
        return 0
    except Exception as e:  # noqa: BLE001 — non-fatal; key may be unencrypted
        print(f"[fetch_secrets] WARNING: could not fetch ssh passphrase "
              f"'{SSH_PASSPHRASE_SECRET_NAME}': {e}", file=sys.stderr)
        return 0
    value = response.get("SecretString")
    if value:
        cfg["BINDGUI_SSH_KEY_PASSPHRASE"] = value
        print(f"[fetch_secrets] loaded SSH key passphrase from {SSH_PASSPHRASE_SECRET_NAME}")
    return 0


def _fetch_secret_config(client) -> int:
    """Write the value-shaped secrets (DB settings + SSH passphrase) from Secrets
    Manager into config.json (0600). Never overwrites an existing config.json —
    a hand-written local override wins."""
    if CONFIG_PATH.exists():
        print(f"[fetch_secrets] {CONFIG_PATH.name} already present — leaving it alone")
        return 0

    cfg: dict[str, str] = {}
    rc = _collect_db_config(client, cfg)
    if rc:
        return rc
    rc |= _collect_ssh_passphrase(client, cfg)

    CONFIG_PATH.write_text(json.dumps(cfg))
    CONFIG_PATH.chmod(0o600)
    print(f"[fetch_secrets] wrote settings {sorted(cfg)} into {CONFIG_PATH.name}")
    return rc


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
    rc |= _fetch_secret_config(client)
    rc |= _fetch_ssh_key(client)
    rc |= _write_known_hosts()
    return rc


if __name__ == "__main__":
    sys.exit(main())
