"""Shared, opt-in results library: binder + per-kinase selectivity metrics.

Backed by RDS Postgres in production (DB_HOST set) and by a local SQLite file in
dev (DB_HOST unset), behind one small portable API. Only runs are stored that
the submitting user explicitly consented to publish.

  public_binders      : one row per published binder (sequence, target, scores)
  public_selectivity  : one row per (binder, kinase) ipTM pair

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
    """Return (connection, placeholder). Placeholder is %s for PG, ? for SQLite."""
    if _pg():
        import psycopg
        conn = psycopg.connect(
            host=config.DB_HOST, port=config.DB_PORT, user=config.DB_USER,
            password=config.DB_PASSWORD, dbname=config.DB_NAME, sslmode="require",
        )
        return conn, "%s"
    import sqlite3
    conn = sqlite3.connect(config.RESULTS_SQLITE)
    conn.row_factory = sqlite3.Row
    return conn, "?"


def init_results_db():
    conn, _ = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
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
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public_selectivity (
                id         TEXT PRIMARY KEY,
                binder_id  TEXT,
                kinase     TEXT,
                best_iptm  REAL,
                avg_iptm   REAL,
                iptm_values TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _rows(cur):
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def publish(job: dict, design: dict, selectivity: list[dict], submitted_by: str):
    """Insert one binder + its per-kinase rows. Idempotent on job_id."""
    conn, ph = _connect()
    try:
        cur = conn.cursor()
        # Skip if this job was already published (idempotent across re-polls).
        cur.execute(f"SELECT id FROM public_binders WHERE job_id = {ph}", (job["id"],))
        if cur.fetchall():
            return
        bid = uuid.uuid4().hex
        cur.execute(
            f"""INSERT INTO public_binders
                (id, job_id, target_name, binder_name, binder_sequence,
                 composite_score, design_metrics, submitted_by, created_at)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
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
            cur.execute(
                f"""INSERT INTO public_selectivity
                    (id, binder_id, kinase, best_iptm, avg_iptm, iptm_values)
                    VALUES ({ph},{ph},{ph},{ph},{ph},{ph})""",
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
    """Published binders (newest first), each with its selectivity rows."""
    conn, ph = _connect()
    try:
        cur = conn.cursor()
        where, args = [], []
        if target:
            where.append(f"target_name = {ph}")
            args.append(target)
        if q:
            where.append(f"(binder_name LIKE {ph} OR binder_sequence LIKE {ph})")
            args += [f"%{q}%", f"%{q}%"]
        if kinase:
            where.append(
                f"id IN (SELECT binder_id FROM public_selectivity WHERE kinase = {ph})"
            )
            args.append(kinase)
        sql = "SELECT * FROM public_binders"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY created_at DESC LIMIT {ph}"
        args.append(limit)
        cur.execute(sql, args)
        binders = _rows(cur)
        if not binders:
            return []
        ids = [b["id"] for b in binders]
        placeholders = ",".join([ph] * len(ids))
        cur.execute(
            f"SELECT * FROM public_selectivity WHERE binder_id IN ({placeholders})", ids
        )
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
