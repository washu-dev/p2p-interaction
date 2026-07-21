"""Declarative config schema — one place that says what each setting *is*.

Phase 1 uses this for two things:
  * validate()  — fail-fast checks so a misconfigured container is caught at
                  startup instead of silently running with a wrong default.
  * redaction   — SENSITIVE names are never printed in cleartext by the
                  effective-config log.

Phase 2 will drive Secrets Manager fetching from the same SENSITIVE/SECRET_NAMES
table, so this stays the single source of truth for "what is secret, what is
required, what is open".
"""

ALL_MODES = {"mock", "slurm", "ssh"}

# Sensitive keys: redacted in logs; must be delivered via Secrets Manager, never
# committed to the open config/<env>.json. (Phase 2: map each to its SM name.)
# The whole DB connection (not just the password) is sourced from the terraform
# MiniBinders/database/* group and materialized into config.json by
# fetch_secrets.py, so host/port/name/user are treated as sensitive too.
SENSITIVE = {
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "BINDGUI_SENDGRID_API_KEY",
    "BINDGUI_SSH_KEY_PASSPHRASE",
}

# Keys that are REQUIRED (must resolve non-empty) in the given backend modes.
REQUIRED_BY_MODE = {
    "BINDGUI_SSH_HOST": {"ssh"},
    "BINDGUI_SSH_USER": {"ssh"},
    "BINDGUI_SSH_KEY": {"ssh"},
    "BINDGUI_SSH_KNOWN_HOSTS_FILE": {"ssh"},
}

# Allowed values for enumerated keys.
CHOICES = {"BINDGUI_BACKEND": ALL_MODES}

# Keys whose code default is a legitimate steady-state value (tunables). A
# DEFAULT source on anything NOT in here is flagged with ⚠ in the startup log,
# since it usually means an environment-identity var was forgotten.
BENIGN_DEFAULTS = {
    "BINDGUI_SSH_PORT",
    "BINDGUI_MOCK_STAGE_SEC",
    "BINDGUI_BACKGROUND_POLL_SEC",
    "BINDGUI_MOCK_PNG",
    "BINDGUI_MOCK_PDB",
    "BUILD_TIME",
    "GIT_SHA",
    "DB_PORT",  # 5432 default is correct everywhere
}


def validate(*, mode: str, env: str, get) -> list[str]:
    """Return a list of human-readable problems (empty == OK).

    `get(name)` returns the resolved value ("" if unset). `mode` is the resolved
    BINDGUI_BACKEND; `env` is BINDGUI_ENV. In `prod` the dangerous fail-open
    defaults (mock backend, empty DB_HOST → SQLite, auth off) are treated as
    errors — those must be explicit, not defaulted.
    """
    problems: list[str] = []

    if mode not in CHOICES["BINDGUI_BACKEND"]:
        problems.append(f"BINDGUI_BACKEND={mode!r} is not one of {sorted(ALL_MODES)}")

    for key, modes in REQUIRED_BY_MODE.items():
        if mode in modes and not get(key):
            problems.append(f"{key} is required when BINDGUI_BACKEND={mode}")

    if env == "prod":
        if mode == "mock":
            problems.append(
                "BINDGUI_BACKEND=mock in prod — set slurm/ssh explicitly "
                "(a real backend), or correct BINDGUI_ENV"
            )
        if not get("DB_HOST"):
            problems.append("DB_HOST is empty in prod — refusing the silent SQLite fallback")
        if str(get("BINDGUI_AUTH_ENABLED")).lower() != "true":
            problems.append("BINDGUI_AUTH_ENABLED must be true in prod")

    return problems
