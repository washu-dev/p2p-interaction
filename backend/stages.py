"""Defines the pipeline DAG as an ordered list of stages.

Each stage maps to one sbatch template (cluster mode) or one simulated step
(mock mode). Stages run in series, each depending on the previous one.

    fold     (only if a FASTA target was uploaded)  ColabFold  -> target.pdb
    design                                          BindCraft  -> top_binder.pdb
    profile                                         profiler   -> result.png
"""

# key -> (label, sbatch template filename)
STAGE_DEFS = {
    "fold": ("Fold target (ColabFold)", "fold_target.sbatch.tmpl"),
    "design": ("Design binders (BindCraft)", "bindcraft.sbatch.tmpl"),
    "profile": ("Profile selectivity → ipTM plot", "profile.sbatch.tmpl"),
}


def build_stages(input_type: str):
    """Ordered runtime stage list for a new job."""
    keys = []
    if input_type == "fasta":
        keys.append("fold")          # FASTA must be folded to a PDB first
    keys += ["design", "profile"]
    return [
        {
            "key": k,
            "label": STAGE_DEFS[k][0],
            "template": STAGE_DEFS[k][1],
            "status": "PENDING",
            "scheduler_id": None,
            "error": None,
        }
        for k in keys
    ]


# Rank: which stage state "wins" when rolling stages up into one job status.
_RANK = {"FAILED": 5, "CANCELLED": 4, "RUNNING": 3, "PENDING": 2, "COMPLETED": 1}


def overall_status(stages):
    if not stages:
        return "PENDING"
    if all(s["status"] == "COMPLETED" for s in stages):
        return "COMPLETED"
    worst = max(stages, key=lambda s: _RANK.get(s["status"], 0))["status"]
    # A failure/cancel anywhere stops the chain.
    if worst in ("FAILED", "CANCELLED"):
        return worst
    # Otherwise we're still making progress.
    return "RUNNING" if any(s["status"] in ("RUNNING", "COMPLETED") for s in stages) else "PENDING"
