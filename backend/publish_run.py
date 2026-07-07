"""Back-load your own BindCraft runs (with files) into the shared results DB.

Enriches the same store the web app reads, via two layers:

  * Scalar/text data  -> reuses resultsdb.publish() (idempotent on job_id):
      who ran it (submitted_by), target_name, binder name/sequence/score,
      design_metrics, and the per-kinase selectivity rows.
  * Files             -> a NEW table `public_binder_artifacts`, one row per
      file (target sequence, target structure, best-binder structure,
      selectivity graph). Stored as bytea (Postgres) / BLOB (SQLite).

Adding files to a new table keeps `public_binders` and the existing
`/api/results` endpoint (which does SELECT *) byte-free and unbroken.

Target DB is chosen exactly like the app: RDS Postgres when DB_HOST/DB_USER/
DB_PASSWORD/DB_NAME are set, else the local SQLite at BINDGUI_RESULTS_SQLITE.

Usage:
    # one run described by a manifest (see example_run.json)
    python publish_run.py path/to/run.json

    # several runs at once
    python publish_run.py runs/*.json

    # don't write — print what WOULD be inserted
    python publish_run.py --dry-run path/to/run.json

All file paths inside a manifest are resolved relative to the manifest's own
location, so a run folder is self-contained and portable.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import mimetypes
import sys
import time
import uuid
from pathlib import Path

import resultsdb  # same dir; provides _connect/_exec/_pg/publish + env-based target

ARTIFACT_KINDS = {
    "target_sequence_file": "target_sequence",
    "target_structure_file": "target_structure",
    "binder_structure_file": "binder_structure",
    "selectivity_graph_file": "selectivity_graph",           # single/combined graph
    "selectivity_graph_avg_file": "selectivity_graph_avg",   # per-kinase avg-ipTM bar chart
    "selectivity_graph_best_file": "selectivity_graph_best",  # per-kinase best-ipTM bar chart
}



def _binder_id_for_job(job_id: str) -> str | None:
    conn = resultsdb._connect()
    try:
        cur = conn.cursor()
        resultsdb._exec(cur, "SELECT id FROM public_binders WHERE job_id = ?", (job_id,))
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _has_artifact(binder_id: str, kind: str) -> bool:
    conn = resultsdb._connect()
    try:
        cur = conn.cursor()
        resultsdb._exec(
            cur,
            "SELECT id FROM public_binder_artifacts WHERE binder_id = ? AND kind = ?",
            (binder_id, kind),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def _insert_artifact(binder_id: str, kind: str, path: Path) -> None:
    content = path.read_bytes()
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    conn = resultsdb._connect()
    try:
        cur = conn.cursor()
        resultsdb._exec(
            cur,
            "INSERT INTO public_binder_artifacts "
            "(id, binder_id, kind, filename, content_type, content, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, binder_id, kind, path.name, ctype, content, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def _resolve(base: Path, value: str | None) -> Path | None:
    if not value:
        return None
    p = Path(value)
    p = p if p.is_absolute() else (base / p)
    if not p.exists():
        raise FileNotFoundError(f"file not found: {p}")
    return p


def publish_manifest(manifest_path: Path, dry_run: bool = False) -> None:
    base = manifest_path.parent
    m = json.loads(manifest_path.read_text())

    # Stable job_id so re-running is idempotent. Derive one if not given.
    job_id = m.get("job_id") or hashlib.sha256(
        json.dumps(m, sort_keys=True).encode()
    ).hexdigest()[:32]

    job = {"id": job_id, "target_name": m.get("target_name"),
           "settings": {"binder_name": m.get("binder_name")}}
    design = {
        "binder_name": m.get("binder_name"),
        "binder_sequence": m.get("binder_sequence"),
        "composite_score": m.get("composite_score"),
        "design_metrics": m.get("design_metrics") or {},
    }
    selectivity = m.get("selectivity") or []
    submitted_by = m.get("submitted_by") or "unknown"

    # Validate file paths up front so a bad manifest fails before any write.
    files = {kind: _resolve(base, m.get(key)) for key, kind in ARTIFACT_KINDS.items()}
    files = {k: v for k, v in files.items() if v is not None}

    label = f"{m.get('target_name')}/{m.get('binder_name')} [job_id={job_id}]"
    if dry_run:
        print(f"[dry-run] would publish {label}")
        print(f"          submitted_by={submitted_by}  score={design['composite_score']}")
        print(f"          selectivity rows: {len(selectivity)}")
        for kind, p in files.items():
            print(f"          file {kind:18s} <- {p}  ({p.stat().st_size} bytes)")
        return

    resultsdb.publish(job, design, selectivity, submitted_by=submitted_by)
    binder_id = _binder_id_for_job(job_id)
    if binder_id is None:
        raise RuntimeError(f"publish() did not create a binder row for {job_id}")

    added = []
    for kind, p in files.items():
        if _has_artifact(binder_id, kind):
            continue  # idempotent: don't duplicate a file already loaded
        _insert_artifact(binder_id, kind, p)
        added.append(kind)
    print(f"published {label} (+{len(added)} files: {', '.join(added) or 'none new'})")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Load BindCraft runs into the shared results DB.")
    ap.add_argument("manifests", nargs="+", help="manifest JSON file(s); globs allowed")
    ap.add_argument("--dry-run", action="store_true", help="print what would be inserted, write nothing")
    args = ap.parse_args(argv)

    paths: list[Path] = []
    for pat in args.manifests:
        hits = [Path(h) for h in glob.glob(pat)] or ([Path(pat)] if Path(pat).exists() else [])
        if not hits:
            print(f"warning: no manifest matched {pat!r}", file=sys.stderr)
        paths += hits
    if not paths:
        print("error: no manifests found", file=sys.stderr)
        return 2

    target = "RDS Postgres" if resultsdb._pg() else f"SQLite ({resultsdb.config.RESULTS_SQLITE})"
    print(f"target DB: {target}")
    resultsdb.init_results_db()  # also ensures public_binder_artifacts now

    for p in paths:
        try:
            publish_manifest(p, dry_run=args.dry_run)
        except Exception as e:  # noqa: BLE001 — report and continue to the next run
            print(f"FAILED {p}: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
