"""Job-tracking + result-cache store.

Portable across two backends behind one small API (same split as resultsdb.py):
  * RDS Postgres in production   — when config.DB_HOST is set. Survives ECS
    task churn / Fargate's ephemeral disk, so job history + the dedup cache
    outlive a redeploy.
  * A local SQLite file in dev   — when config.DB_HOST is unset (config.DB_PATH).

A job stores its `stages` (the fold/design/profile DAG, as JSON) and a
`params_key` (hash of its inputs) so an identical, already-COMPLETED run can be
offered back instead of re-running the whole pipeline on the cluster.

SQL-injection safety: SQL is always written with constant `?` placeholders and
every value is passed separately as a bound parameter. Column *identifiers* in
the dynamic INSERT/UPDATE are validated against the `_COLUMNS` allowlist, so they
can never be attacker-controlled. `_exec()` is the single place that talks to a
cursor; it only swaps the placeholder token for psycopg.

psycopg is imported lazily so dev without Postgres needs no extra deps.
"""
import json
import time

import config

# Columns whose values are stored as JSON text.
_JSON_COLS = {"settings", "stages"}

# Every column the dynamic INSERT/UPDATE statements are allowed to name. Column
# identifiers can't be bound as parameters, so we validate them against this
# allowlist — guaranteeing they can never be attacker-controlled (defense in
# depth; values are already passed as bound parameters).
_COLUMNS = {
    "id", "name", "status", "params_key", "mode", "input_type", "target_name",
    "settings", "stages", "result_path", "error", "created_at", "updated_at",
    "notified", "published",
}


def _pg() -> bool:
    return bool(config.DB_HOST)


def _connect():
    if _pg():
        import psycopg
        return psycopg.connect(
            host=config.DB_HOST, port=config.DB_PORT, user=config.DB_USER,
            password=config.DB_PASSWORD, dbname=config.DB_NAME, sslmode="require",
        )
    import sqlite3
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _exec(cur, sql: str, args: tuple | list = ()):
    """Execute a `?`-placeholder query, binding all values as parameters.

    Values are NEVER formatted into `sql`; we only translate the placeholder
    token to psycopg's `%s`. This keeps every query parameterized by design.

    A parameterless query is sent with no params at all: psycopg only scans for
    `%s` placeholders when parameters are supplied, so this keeps a stray `%`/`?`
    in DDL text (e.g. inside an SQL comment) from being miscounted as a
    placeholder — which would raise "N placeholders but 0 parameters were passed".
    """
    if _pg():
        sql = sql.replace("?", "%s")
        cur.execute(sql, args if args else None)
    else:
        cur.execute(sql, args)


def _rows(cur):
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]


def _check_cols(d):
    unknown = set(d) - _COLUMNS
    if unknown:
        raise ValueError(f"unknown job column(s): {sorted(unknown)}")


def _encode(d):
    return {k: (json.dumps(v) if k in _JSON_COLS else v) for k, v in d.items()}


def _decode(d):
    """Parse JSON columns back into Python objects on a plain result dict."""
    if d is None:
        return None
    for col in _JSON_COLS:
        d[col] = json.loads(d[col]) if d.get(col) else ([] if col == "stages" else {})
    return d


def init_db():
    # TEXT + DOUBLE PRECISION are portable: SQLite gives them TEXT/REAL affinity,
    # Postgres gives text/float8 (float8 is needed so epoch timestamps keep full
    # precision — a single-precision REAL would truncate them).
    conn = _connect()
    try:
        cur = conn.cursor()
        _exec(cur, """
            CREATE TABLE IF NOT EXISTS jobs (
                id           TEXT PRIMARY KEY,
                name         TEXT,
                status       TEXT,
                params_key   TEXT,
                mode         TEXT,
                input_type   TEXT,             -- 'fasta' | 'pdb'
                target_name  TEXT,
                settings     TEXT,             -- json
                stages       TEXT,             -- json list
                result_path  TEXT,
                error        TEXT,
                created_at   DOUBLE PRECISION,
                updated_at   DOUBLE PRECISION,
                notified     INTEGER DEFAULT 0,  -- email sent for this terminal state
                published    INTEGER DEFAULT 0   -- published to the binder library
            )
        """)
        _exec(cur, "CREATE INDEX IF NOT EXISTS idx_params_key ON jobs(params_key)")
        conn.commit()
        # CREATE TABLE IF NOT EXISTS is a no-op on a table that predates the
        # notified/published columns — add them directly, but only when they're
        # actually missing: ALTER TABLE ADD COLUMN takes a brief ACCESS EXCLUSIVE
        # lock in Postgres, and during an ECS rolling deploy the outgoing task is
        # still holding connections against the same table. Checking first means
        # a healthy, already-migrated deploy never attempts the ALTER at all; a
        # lock_timeout bounds the rare case where it's genuinely still needed, so
        # a new task can never hang its own startup (and thus its health check)
        # waiting on a lock the old task is holding.
        for col in ("notified", "published"):
            if _has_column(conn, "jobs", col):
                continue
            try:
                if _pg():
                    _exec(cur, "SET lock_timeout = '5s'")
                _exec(cur, f"ALTER TABLE jobs ADD COLUMN {col} INTEGER DEFAULT 0")
                conn.commit()
            except Exception as e:  # noqa: BLE001 — lock contention; safe to skip, retried next startup
                conn.rollback()
                print(f"[db] could not add column '{col}' this startup (will retry next deploy): {e}")
    finally:
        conn.close()


def _has_column(conn, table: str, col: str) -> bool:
    cur = conn.cursor()
    if _pg():
        _exec(cur, "SELECT 1 FROM information_schema.columns WHERE table_name = ? AND column_name = ?", (table, col))
        return cur.fetchone() is not None
    cur.execute(f"PRAGMA table_info({table})")  # noqa: S608 — table name is a hardcoded literal, never user input
    return any(r[1] == col for r in cur.fetchall())


def create_job(job):
    enc = _encode(job)
    _check_cols(enc)  # identifiers are allowlisted; values below are bound
    cols = list(enc)
    col_sql = ", ".join(cols)
    ph = ", ".join(["?"] * len(cols))
    conn = _connect()
    try:
        cur = conn.cursor()
        _exec(cur, f"INSERT INTO jobs ({col_sql}) VALUES ({ph})", [enc[c] for c in cols])  # noqa: S608
        conn.commit()
    finally:
        conn.close()


def update_job(job_id, **fields):
    if not fields:
        return
    fields["updated_at"] = time.time()
    enc = _encode(fields)
    _check_cols(enc)  # identifiers are allowlisted; values below are bound
    cols = list(enc)
    sets = ", ".join(f"{c} = ?" for c in cols)
    conn = _connect()
    try:
        cur = conn.cursor()
        _exec(cur, f"UPDATE jobs SET {sets} WHERE id = ?", [enc[c] for c in cols] + [job_id])  # noqa: S608
        conn.commit()
    finally:
        conn.close()


def get_job(job_id):
    conn = _connect()
    try:
        cur = conn.cursor()
        _exec(cur, "SELECT * FROM jobs WHERE id = ?", (job_id,))
        rows = _rows(cur)
        return _decode(rows[0]) if rows else None
    finally:
        conn.close()


def list_jobs(limit=200):
    conn = _connect()
    try:
        cur = conn.cursor()
        _exec(cur, "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [_decode(r) for r in _rows(cur)]
    finally:
        conn.close()


def find_cached(params_key):
    conn = _connect()
    try:
        cur = conn.cursor()
        _exec(
            cur,
            "SELECT * FROM jobs WHERE params_key = ? AND status = 'COMPLETED' "
            "ORDER BY created_at DESC LIMIT 1",
            (params_key,),
        )
        rows = _rows(cur)
        return _decode(rows[0]) if rows else None
    finally:
        conn.close()
