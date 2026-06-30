"""Shared, opt-in results library: binder + per-kinase selectivity metrics.

Backed by RDS Postgres in production (DB_HOST set) and by a local SQLite file in
dev (DB_HOST unset), behind one small portable API. Only runs are stored that
the submitting user explicitly consented to publish.

  public_binders      : one row per published binder (sequence, target, scores)
  public_selectivity  : one row per (binder, kinase) ipTM pair

SQL injection safety: SQL is always written with constant `?` placeholders and
every value is passed separately as a bound parameter — no caller ever
interpolates user input into a query string. `_exec()` is the single place that
talks to a DB cursor; it only swaps the placeholder token for psycopg.

psycopg is imported lazily so dev without Postgres needs no extra deps.
"""
from __future__ import annotations

import json
import time
import uuid

import config


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
    conn = sqlite3.connect(config.RESULTS_SQLITE)
    conn.row_factory = sqlite3.Row
    return conn


def _exec(cur, sql: str, args: tuple | list = ()):
    """Execute a `?`-placeholder query, binding all values as parameters.

    Values are NEVER formatted into `sql`; we only translate the placeholder
    token to psycopg's `%s`. This keeps every query parameterized by design.
    """
    if _pg():
        sql = sql.replace("?", "%s")
    cur.execute(sql, args)


def init_results_db():
    conn = _connect()
    try:
        cur = conn.cursor()
        _exec(cur, """
            CREATE TABLE IF NOT EXISTS public_binders (
                id              TEXT PRIMARY KEY,
                job_id          TEXT UNIQUE,
                target_name     TEXT,
                binder_name     TEXT,
                binder_sequence TEXT,
                composite_score REAL,
                design_metrics  TEXT,
                submitted_by    TEXT,
                created_at      REAL
            )
        """)
        _exec(cur, """
            CREATE TABLE IF NOT EXISTS public_selectivity (
                id         TEXT PRIMARY KEY,
                binder_id  TEXT,
                kinase     TEXT,
                best_iptm  REAL,
                avg_iptm   REAL,
                iptm_values TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()


def _rows(cur):
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]


def publish(job: dict, design: dict, selectivity: list[dict], submitted_by: str):
    """Insert one binder + its per-kinase rows. Idempotent on job_id."""
    conn = _connect()
    try:
        cur = conn.cursor()
        # Skip if this job was already published (idempotent across re-polls).
        _exec(cur, "SELECT id FROM public_binders WHERE job_id = ?", (job["id"],))
        if cur.fetchall():
            return
        bid = uuid.uuid4().hex
        _exec(
            cur,
            "INSERT INTO public_binders "
            "(id, job_id, target_name, binder_name, binder_sequence, "
            "composite_score, design_metrics, submitted_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                bid, job["id"], job.get("target_name"),
                design.get("binder_name") or job.get("settings", {}).get("binder_name"),
                design.get("binder_sequence"),
                design.get("composite_score"),
                json.dumps(design.get("design_metrics") or {}),
                submitted_by, time.time(),
            ),
        )
        for s in selectivity:
            _exec(
                cur,
                "INSERT INTO public_selectivity "
                "(id, binder_id, kinase, best_iptm, avg_iptm, iptm_values) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    uuid.uuid4().hex, bid, s.get("kinase"),
                    s.get("best_iptm"), s.get("avg_iptm"),
                    json.dumps(s.get("iptm_values") or []),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def list_results(kinase: str | None = None, target: str | None = None,
                 q: str | None = None, limit: int = 200) -> list[dict]:
    """Published binders (newest first), each with its selectivity rows.

    All filters are bound parameters; only fixed condition fragments (no user
    data) are assembled into the WHERE clause.
    """
    conn = _connect()
    try:
        cur = conn.cursor()
        conditions, args = [], []
        if target:
            conditions.append("target_name = ?")
            args.append(target)
        if q:
            conditions.append("(binder_name LIKE ? OR binder_sequence LIKE ?)")
            args += [f"%{q}%", f"%{q}%"]
        if kinase:
            conditions.append("id IN (SELECT binder_id FROM public_selectivity WHERE kinase = ?)")
            args.append(kinase)
        sql = "SELECT * FROM public_binders"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        _exec(cur, sql, args)
        binders = _rows(cur)
        if not binders:
            return []

        ids = [b["id"] for b in binders]
        # in_clause is only "?, ?, ..." placeholder tokens — never any user data;
        # the binder ids are passed as bound parameters below.
        in_clause = ", ".join(["?"] * len(ids))
        _exec(cur, "SELECT * FROM public_selectivity WHERE binder_id IN (" + in_clause + ")", ids)  # noqa: S608
        sel_by_binder: dict[str, list] = {}
        for s in _rows(cur):
            sel_by_binder.setdefault(s["binder_id"], []).append(
                {"kinase": s["kinase"], "best_iptm": s["best_iptm"], "avg_iptm": s["avg_iptm"]}
            )
        for b in binders:
            b["design_metrics"] = json.loads(b.get("design_metrics") or "{}")
            b["selectivity"] = sorted(sel_by_binder.get(b["id"], []), key=lambda x: x["kinase"])
        return binders
    finally:
        conn.close()
