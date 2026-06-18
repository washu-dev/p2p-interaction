"""Pick the top-ranked accepted binder PDB from a BindCraft output dir.

Usage:
    python select_top_binder.py <bindcraft_out_dir> <dest.pdb>

Strategy (best-effort, tolerant of layout differences):
  1. If final_design_stats.csv exists, take the design named in its first data
     row (BindCraft writes that file ranked best-first) and find its PDB.
  2. Otherwise fall back to the most recently written *.pdb under Accepted/.
The chosen PDB is copied to <dest.pdb> for the profiling stage.
"""
import csv
import glob
import os
import shutil
import sys


def find_pdb(root, design_name):
    # design_name may or may not carry the .pdb suffix.
    stem = design_name[:-4] if design_name.lower().endswith(".pdb") else design_name
    hits = glob.glob(os.path.join(root, "**", stem + ".pdb"), recursive=True)
    return hits[0] if hits else None


def from_csv(out_dir):
    csv_path = os.path.join(out_dir, "final_design_stats.csv")
    if not os.path.exists(csv_path):
        return None
    with open(csv_path, newline="") as f:
        rows = list(csv.reader(f))
    if len(rows) < 2:
        return None
    header, first = rows[0], rows[1]
    # Locate the design-name column (commonly "Design" / "design_name" / col 0).
    idx = 0
    for i, h in enumerate(header):
        if h.strip().lower() in ("design", "design_name", "name"):
            idx = i
            break
    return find_pdb(out_dir, first[idx].strip())


def newest_accepted(out_dir):
    cands = glob.glob(os.path.join(out_dir, "**", "Accepted", "*.pdb"), recursive=True)
    if not cands:
        cands = glob.glob(os.path.join(out_dir, "**", "*.pdb"), recursive=True)
    return max(cands, key=os.path.getmtime) if cands else None


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    out_dir, dest = sys.argv[1], sys.argv[2]

    top = from_csv(out_dir) or newest_accepted(out_dir)
    if not top or not os.path.exists(top):
        print(f"ERROR: no binder PDB found under {out_dir}", file=sys.stderr)
        sys.exit(1)

    shutil.copyfile(top, dest)
    print(f"Top binder: {top} -> {dest}")


if __name__ == "__main__":
    main()
