# 06 — Configuration & secrets management

One environment's configuration lives in **one place**, split by sensitivity:

- **Open (committed to git):** `backend/config/<env>.json` — everything non-secret
  for that environment, selected by `BINDGUI_ENV` (`dev` | `staging` | `prod`).
- **Sensitive (AWS Secrets Manager, terraform-managed):** the whole DB
  connection (host/port/name/user/password, from the `MiniBinders/database/*`
  group), SendGrid key, SSH passphrase/key — never committed, materialized at
  container startup by `fetch_secrets.py`. `config_loader` strips any sensitive
  key that slips into an open file (and warns), so the split can't be bypassed.
- **Schema (`backend/configschema.py`):** the single declaration of which keys
  are sensitive, which are required in which backend mode, and which defaults
  are benign. Drives validation and log redaction (and, in Phase 2, the Secrets
  Manager fetch).

## Resolution precedence (high → low)

Implemented in `backend/config_loader.py`; every module reads via `config.py`.

1. **Process env var** — ad-hoc / CI / local override.
2. **`backend/config.json`** — secrets written at startup by `fetch_secrets.py`
   (DB creds from Secrets Manager). Git-ignored.
3. **`backend/config/<env>.json`** — committed open per-env values.
4. **Code default** — benign tunables only; environment-identity keys have none.

`BINDGUI_ENV` is env-only (it selects the open file). The SSH credential trio
(`BINDGUI_SSH_KEY` / `BINDGUI_SSH_KEY_PASSPHRASE` / `BINDGUI_SSH_KNOWN_HOSTS_FILE`)
and `GIT_SHA` / `BINDGUI_SLURM_ACCOUNT` are also env-only.

## Fail-fast validation (closes the fail-open-default gap)

`config.validate()` runs at startup (`main.py`). It rejects:
- an invalid `BINDGUI_BACKEND`;
- missing SSH credentials when `BINDGUI_BACKEND=ssh`;
- in **`prod`**, the dangerous silent defaults — `mock` backend, empty `DB_HOST`
  (→ SQLite on ephemeral disk), and `AUTH_ENABLED` off.

**Phase 1 is warn-only** (logs problems, never aborts) so rollouts aren't blocked
while `config/<env>.json` is still being filled in. Phase 3 flips it to a hard
`SystemExit`, so a misconfigured container fails its deploy instead of silently
serving wrong behavior.

## Effective-config log

`config.effective_config_log()` prints, at startup, every resolved key with its
value and **source** (`env` / `config.json` / `config/<env>.json` / `DEFAULT`).
Sensitive keys show `set (len N)` / `MISSING`, never their value. A `⚠` marks any
identity key that fell through to a default — the usual sign of a forgotten var.

## Local testing

Config resolves at import, so: `BINDGUI_ENV=<env> python3 -c "import config;
print(config.effective_config_log()); print(config.validate())"`. Regression
tests: `python3 backend/tests/test_config.py`. Locally the DB falls back to
SQLite (no RDS reachability needed); the loader/validation/log path is identical
to prod.

## Rollout status

- ✅ **Phase 1** — schema + loader + `config/<env>.json` + warn-only validation +
  effective-config log. Non-breaking (env still wins), tested.
- 🟡 **Phase 2 (in progress)** — SSH secrets wired: `fetch_secrets.py`
  materializes the file-shaped key (`MiniBinders/ssh/PRIVATE_KEY` →
  `BINDGUI_SSH_KEY`, chmod 600) and reads the optional value-shaped passphrase
  (`MiniBinders/ssh/KEY_PASSPHRASE`, derived from the key's group) into
  `config.json`. Still to do: move the SendGrid key out of the plaintext task-def
  env into Secrets Manager (**rotate it** — it was stored in cleartext); add the
  `notify/*` terraform group.
- ⬜ **Phase 3** — remove now-redundant env vars from the task definition (rely on
  `config/prod.json`), set `BINDGUI_ENV=prod`, flip validation to fail-fast.
- ⬜ **Phase 4** — migrate to `pydantic-settings` (typed/required fields); load the
  SSH key in-memory.
