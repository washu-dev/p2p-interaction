"""Pick the best binder from a BindCraft run via a weighted composite score.

Usage:
    python select_top_binder.py <bindcraft_out_dir> <dest.pdb>

Reads <bindcraft_out_dir>/final_design_stats.csv, scores every design with a
weighted, min-max-normalised composite across many AF2 / Rosetta / H-bond /
RMSD / sequence / clash metrics, picks the highest-scoring design, locates its
<Design>.pdb (preferring an Accepted/ dir), and copies it to <dest.pdb>.

Also writes <dest_dir>/design_result.json (binder name, sequence, composite
score, and key metrics) for the binder library. Pure standard library;
falls back to the newest Accepted/*.pdb if the stats CSV is missing/unusable.
"""
import csv
import glob
import json
import os
import shutil
import sys

# (column, weight, higher_is_better). Weights are relative; normalised internally.
METRICS = [
    ("Average_i_pTM", 10, True),
    ("Average_pLDDT", 7, True),
    ("Average_i_pLDDT", 8, True),
    ("Average_ss_pLDDT", 5, True),
    ("Average_pTM", 6, True),
    ("Average_i_pAE", 8, False),
    ("Average_pAE", 5, False),
    ("Average_dG/dSASA", 10, False),
    ("Average_ShapeComplementarity", 9, True),
    ("Average_PackStat", 8, True),
    ("Average_dG", 7, False),
    ("Average_dSASA", 5, True),
    ("Average_Binder_Energy_Score", 4, False),
    ("Average_InterfaceHbondsPercentage", 7, True),
    ("Average_n_InterfaceHbonds", 5, True),
    ("Average_n_InterfaceUnsatHbonds", 8, False),
    ("Average_Hotspot_RMSD", 10, False),
    ("Average_Target_RMSD", 6, False),
    ("Average_Binder_RMSD", 5, False),
    ("Average_Binder_pLDDT", 8, True),
    ("Average_Binder_pTM", 7, True),
    ("Average_Binder_pAE", 6, False),
    ("MPNN_score", 7, True),
    ("MPNN_seq_recovery", 4, True),
    ("Average_Relaxed_Clashes", 9, False),
    ("Average_Unrelaxed_Clashes", 6, False),
    ("Average_Surface_Hydrophobicity", 5, False),
]


def _fnum(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def score_designs(rows):
    """Return (design, score) sorted best-first, plus skipped columns."""
    skipped = []
    normed = {}
    for col, weight, higher in METRICS:
        if not rows or col not in rows[0]:
            skipped.append(col)
            continue
        raw = [_fnum(r.get(col)) for r in rows]
        present = [v for v in raw if v is not None]
        if len(present) < 2:
            skipped.append(col)
            continue
        lo, hi = min(present), max(present)
        out = []
        for v in raw:
            if v is None or hi == lo:
                out.append(0.5)
            else:
                n = (v - lo) / (hi - lo)
                out.append(n if higher else 1.0 - n)
        normed[col] = (out, weight)

    total_w = sum(w for _, w in normed.values())
    scored = []
    for i, r in enumerate(rows):
        s = sum(out[i] * w for out, w in normed.values()) / total_w * 100.0 if total_w else 0.0
        scored.append((r.get("Design", "").strip(), round(s, 3)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored, skipped


def design_metrics(row):
    """Curated numeric metrics for the results library."""
    out = {}
    for col, _, _ in METRICS:
        v = _fnum(row.get(col))
        if v is not None:
            out[col] = v
    return out


def from_csv(out_dir):
    """Return (pdb_path, design_dict) for the top binder, or None."""
    csv_path = os.path.join(out_dir, "final_design_stats.csv")
    if not os.path.exists(csv_path):
        return None
    with open(csv_path, newline="") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("Design") or "").strip()]
    if not rows:
        return None

    scored, skipped = score_designs(rows)
    if not scored:
        return None

    print("=" * 64)
    print("  BindCraft binder scoring - weighted composite")
    print("=" * 64)
    for rank, (design, sc) in enumerate(scored, 1):
        star = " *" if rank == 1 else "  "
        print(f"{star} {rank:>3}. {sc:>7.3f}  {design}")
    if skipped:
        print(f"  (skipped columns: {skipped})")

    top_name, top_score = scored[0]
    top_row = next((r for r in rows if (r.get("Design") or "").strip() == top_name), {})
    print(f"\n  TOP: {top_name}  (composite {top_score:.3f}/100)")

    pdb = find_pdb(out_dir, top_name)
    design = {
        "binder_name": top_name,
        "binder_sequence": (top_row.get("Sequence") or "").strip(),
        "composite_score": top_score,
        "design_metrics": design_metrics(top_row),
        # final_design_stats.csv has one row per BindCraft-accepted design.
        "accepted_designs": len(scored),
    }
    return pdb, design


def find_pdb(root, design_name):
    stem = design_name[:-4] if design_name.lower().endswith(".pdb") else design_name
    # BindCraft names the accepted file <Design>_model<N>.pdb, while the stats CSV
    # 'Design' column has no _model suffix — so match by prefix, not exact name.
    # The Accepted/Ranked/ copies are prefixed (e.g. "1_<Design>..."), so a
    # "<stem>*.pdb" glob naturally prefers the clean Accepted/<stem>_model*.pdb.
    for pattern in (
        os.path.join(root, "**", "Accepted", stem + "*.pdb"),
        os.path.join(root, "**", stem + "*.pdb"),
    ):
        hits = sorted(glob.glob(pattern, recursive=True))
        if hits:
            return hits[0]
    return None


def newest_accepted(out_dir):
    cands = glob.glob(os.path.join(out_dir, "**", "Accepted", "*.pdb"), recursive=True)
    if not cands:
        cands = glob.glob(os.path.join(out_dir, "**", "*.pdb"), recursive=True)
    return max(cands, key=os.path.getmtime) if cands else None


def count_accepted(out_dir):
    return len(glob.glob(os.path.join(out_dir, "**", "Accepted", "*.pdb"), recursive=True))


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    out_dir, dest = sys.argv[1], sys.argv[2]

    result = from_csv(out_dir)
    if result:
        top, design = result
    else:
        print("Composite scoring unavailable - falling back to newest Accepted/*.pdb")
        top, design = newest_accepted(out_dir), {"accepted_designs": count_accepted(out_dir)}

    if not top or not os.path.exists(top):
        print(f"ERROR: no binder PDB found under {out_dir}", file=sys.stderr)
        sys.exit(1)

    shutil.copyfile(top, dest)
    # Emit machine-readable design result next to the chosen PDB (the job dir).
    if design:
        with open(os.path.join(os.path.dirname(dest) or ".", "design_result.json"), "w") as f:
            json.dump(design, f, indent=2)
    print(f"Top binder: {top} -> {dest}")


if __name__ == "__main__":
    main()
