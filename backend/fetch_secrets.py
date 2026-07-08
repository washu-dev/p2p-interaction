"""Populate backend/config.json from AWS Secrets Manager at container startup.

Run by entrypoint.sh before uvicorn starts. Writes only the keys we actually
fetch (currently DB_PASSWORD) — every other DB setting (host/port/user/name)
stays a plain ECS task-definition environment variable, since those aren't
sensitive on their own. config.py's _db_setting() prefers config.json over
the environment, so this file only needs to carry the secret values.

Intentionally skipped unless BINDGUI_FETCH_SECRETS=true (local/dev has no AWS
access and no RDS to connect to by default) or when config.json already
exists (a developer's hand-written local override wins and is never
clobbered). Deliberately independent of BINDGUI_BACKEND — the DB connection
and the job-execution runner (mock/slurm/ssh) are unrelated concerns, and a
deployment may want real Postgres while still simulating jobs, or vice versa.
"""
import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

DB_PASSWORD_SECRET_NAME = os.environ.get("BINDGUI_DB_PASSWORD_SECRET", "MINIBINDERS-DBPASSWORD")
AWS_REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"


def main() -> int:
    if os.environ.get("BINDGUI_FETCH_SECRETS", "false").lower() != "true":
        print("[fetch_secrets] BINDGUI_FETCH_SECRETS not set to true — skipping Secrets Manager fetch")
        return 0

    if CONFIG_PATH.exists():
        print(f"[fetch_secrets] {CONFIG_PATH.name} already present — leaving it alone")
        return 0

    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    client = boto3.client("secretsmanager", region_name=AWS_REGION)
    try:
        response = client.get_secret_value(SecretId=DB_PASSWORD_SECRET_NAME)
    except (BotoCoreError, ClientError) as e:
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


if __name__ == "__main__":
    sys.exit(main())
