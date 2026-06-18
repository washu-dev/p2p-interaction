"""SQLite layer for job tracking + result caching.

A job stores its `stages` (the fold/design/profile DAG, as JSON) and a
`params_key` (hash of its inputs) so an identical, already-COMPLETED run can be
offered back instead of re-running the whole pipeline on the cluster.
"""
import json
import sqlite3
import time

import config

# Columns whose values are stored as JSON text.
_JSON_COLS = {"settings", "stages"}


def _conn():
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id           TEXT PRIMARY KEY,
                name         TEXT,
                status       TEXT,
                params_key   TEXT,
                mode         TEXT,
                input_type   TEXT,    -- 'fasta' | 'pdb'
                target_name  TEXT,
                settings     TEXT,    -- json
                stages       TEXT,    -- json list
                result_path  TEXT,
                error        TEXT,
                created_at   REAL,
                updated_at   REAL
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_params_key ON jobs(params_key)")


def _encode(d):
    return {k: (json.dumps(v) if k in _JSON_COLS else v) for k, v in d.items()}


def _row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    for col in _JSON_COLS:
        d[col] = json.loads(d[col]) if d.get(col) else ([] if col == "stages" else {})
    return d


def create_job(job):
    enc = _encode(job)
    cols = ", ".join(enc)
    ph = ", ".join(f":{k}" for k in enc)
    with _conn() as c:
        c.execute(f"INSERT INTO jobs ({cols}) VALUES ({ph})", enc)


def update_job(job_id, **fields):
    if not fields:
        return
    fields["updated_at"] = time.time()
    enc = _encode(fields)
    sets = ", ".join(f"{k} = ?" for k in enc)
    with _conn() as c:
        c.execute(f"UPDATE jobs SET {sets} WHERE id = ?", [*enc.values(), job_id])


def get_job(job_id):
    with _conn() as c:
        return _row_to_dict(
            c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        )


def list_jobs(limit=200):
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def find_cached(params_key):
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM jobs WHERE params_key = ? AND status = 'COMPLETED' "
            "ORDER BY created_at DESC LIMIT 1",
            (params_key,),
        ).fetchone()
    return _row_to_dict(row)
