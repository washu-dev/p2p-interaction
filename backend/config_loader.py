"""Layered configuration loader — the single resolution point for settings.

Precedence per key (high → low):

  1. process environment variable           (ad-hoc / CI / local override)
  2. backend/config.json                     (secrets written at startup by
                                              fetch_secrets.py, e.g. DB creds)
  3. backend/config/<env>.json               (committed, OPEN per-env values;
                                              <env> = BINDGUI_ENV, default "dev")
  4. code default                            (benign tunables only)

`BINDGUI_ENV` selects the committed open file, so a whole environment's
non-secret config lives in one versioned place, while its secrets live in AWS
Secrets Manager (materialized into config.json). The loader records the SOURCE
and value of every resolved key so config.py can print an effective-config table
at startup (see config.effective_config_log) and redact the sensitive ones.
"""
import json
import os
from pathlib import Path

import configschema

BASE_DIR = Path(__file__).resolve().parent
RUNTIME_CONFIG = BASE_DIR / "config.json"        # written by fetch_secrets.py (secrets)
ENV_CONFIG_DIR = BASE_DIR / "config"             # committed open per-env files

# The environment name is itself env-only (it selects the open file, so it
# cannot come from that file). Defaults to "dev" so local runs need nothing set.
ENV = (os.environ.get("BINDGUI_ENV") or "dev").strip().lower()


def _read_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:  # malformed → ignore, fall through
            print(f"[config] ignoring unreadable {path}: {e}")
    return {}


_RUNTIME = _read_json(RUNTIME_CONFIG)
_OPEN = _read_json(ENV_CONFIG_DIR / f"{ENV}.json")

# Enforce the split: a sensitive key must never be served from the committed
# open file (it belongs in Secrets Manager). Drop any that slipped in, loudly.
_leaked = sorted(set(_OPEN) & configschema.SENSITIVE)
if _leaked:
    print(f"[config] WARNING: ignoring sensitive key(s) found in config/{ENV}.json "
          f"(must come from Secrets Manager, not the committed file): {_leaked}")
    for _k in _leaked:
        _OPEN.pop(_k, None)

# name -> (resolved_value, source_label); populated as keys are resolved so the
# startup log reflects exactly what the app is running with.
_resolved: dict[str, tuple[str, str]] = {}


def _record(name: str, value, source: str):
    _resolved[name] = ("" if value is None else str(value), source)


def get(name: str, default="", *, env_only: bool = False):
    """Resolve `name` by precedence; record its source. Empty string counts as
    unset so a blank env var/file entry falls through instead of masking a
    real value further down the chain. `env_only=True` skips both JSON layers
    (for values that must never live in a config file, e.g. secret file paths)."""
    val = os.environ.get(name)
    if val not in (None, ""):
        _record(name, val, "env")
        return val
    if not env_only:
        val = _RUNTIME.get(name)
        if val not in (None, ""):
            _record(name, val, "config.json")
            return val
        val = _OPEN.get(name)
        if val not in (None, ""):
            _record(name, val, f"config/{ENV}.json")
            return val
    _record(name, default, "DEFAULT")
    return default


def resolved() -> dict[str, tuple[str, str]]:
    """{name: (value, source)} for every key resolved so far."""
    return dict(_resolved)
