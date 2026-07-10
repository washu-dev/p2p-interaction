"""Shared target library: FASTA/PDB target files anyone can search and reuse.

Two ways a target lands here:
  * fetched from UniProt by gene/protein name (search -> pick -> download)
  * uploaded directly by a user who already has the FASTA/PDB file

Unlike the results library (resultsdb.py), publishing here is NOT opt-in —
every target a user adds is saved so the next person doesn't have to re-fetch
or re-upload the same kinase. File bytes live on disk under
config.LIBRARY_TARGETS_DIR; this module only tracks the metadata + lookup.

Same Postgres (prod) / SQLite (dev) split as resultsdb.py, behind one API.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

import config


def _pg() -> bool:
    return bool(config.DB_HOST)


def _connect():
    if _pg():
        import psycopg
        conn = psycopg.connect(
            host=config.DB_HOST, port=config.DB_PORT, user=config.DB_USER,
            password=config.DB_PASSWORD, dbname=config.DB_NAME, sslmode="require",
        )
        return conn, "%s"
    import sqlite3
    conn = sqlite3.connect(config.LIBRARY_SQLITE)
    conn.row_factory = sqlite3.Row
    return conn, "?"


def init_library_db():
    conn, _ = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS library_targets (
                id            TEXT PRIMARY KEY,
                name          TEXT,
                input_type    TEXT,   -- 'fasta' | 'pdb'
                source        TEXT,   -- 'uniprot' | 'upload'
                accession     TEXT,
                organism      TEXT,
                file_name     TEXT,
                sequence_preview TEXT,
                submitted_by  TEXT,
                created_at    REAL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _rows(cur):
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]


def _file_path(target_id: str, input_type: str) -> Path:
    ext = "fasta" if input_type == "fasta" else "pdb"
    return config.LIBRARY_TARGETS_DIR / f"{target_id}.{ext}"


def add_target(
    name: str,
    input_type: str,
    data: bytes,
    source: str,
    submitted_by: str,
    accession: str = "",
    organism: str = "",
) -> dict:
    """Store the file on disk + a metadata row; returns the new row."""
    tid = uuid.uuid4().hex
    _file_path(tid, input_type).write_bytes(data)
    preview = ""
    if input_type == "fasta":
        preview = data.decode("utf-8", errors="replace").splitlines()[0][:200] if data else ""
    row = {
        "id": tid, "name": name, "input_type": input_type, "source": source,
        "accession": accession, "organism": organism,
        "file_name": f"{name}.{ 'fasta' if input_type == 'fasta' else 'pdb' }",
        "sequence_preview": preview, "submitted_by": submitted_by, "created_at": time.time(),
    }
    conn, ph = _connect()
    try:
        cur = conn.cursor()
        cols = ", ".join(row)
        vals = ", ".join([ph] * len(row))
        cur.execute(f"INSERT INTO library_targets ({cols}) VALUES ({vals})", list(row.values()))  # noqa: S608
        conn.commit()
    finally:
        conn.close()
    return row


def list_targets(q: str | None = None, input_type: str | None = None, limit: int = 200) -> list[dict]:
    conn, ph = _connect()
    try:
        cur = conn.cursor()
        where, args = [], []
        if q:
            where.append(f"(name LIKE {ph} OR accession LIKE {ph})")
            args += [f"%{q}%", f"%{q}%"]
        if input_type:
            where.append(f"input_type = {ph}")
            args.append(input_type)
        sql = "SELECT * FROM library_targets"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY created_at DESC LIMIT {ph}"
        args.append(limit)
        cur.execute(sql, args)  # noqa: S608
        return _rows(cur)
    finally:
        conn.close()


def get_target(target_id: str) -> dict | None:
    conn, ph = _connect()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM library_targets WHERE id = {ph}", (target_id,))  # noqa: S608 — `ph` is a fixed placeholder, not user input
        rows = _rows(cur)
        return rows[0] if rows else None
    finally:
        conn.close()


def read_file(target_id: str, input_type: str) -> bytes:
    return _file_path(target_id, input_type).read_bytes()
