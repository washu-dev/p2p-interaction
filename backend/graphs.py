"""Server-side selectivity graphs for the binder library.

Renders an average-ipTM bar chart for a published binder, either across the whole
kinase panel or filtered to one Manning family (the binder's target kinase is
always included and highlighted). Styling mirrors the cluster-side plot in
`pipeline/ipTM2graph.py` (0.6 / 0.8 confidence zones + reference lines).

Uses the non-interactive Agg backend so it runs headless in the API container.
"""
from __future__ import annotations

import io

import kinase_families
import matplotlib

matplotlib.use("Agg")  # headless: no display; must run before pyplot is imported
import matplotlib.pyplot as plt  # noqa: E402


def avg_iptm_png(target_name: str, rows: list[dict], family: str | None = None) -> bytes:
    """PNG bytes of an average-ipTM bar chart.

    rows: [{"kinase": str, "avg_iptm": float|None}, ...]
    family: None -> whole panel; otherwise only kinases in that Manning group,
            plus the target kinase (highlighted even if outside the group).
    """
    target_u = (target_name or "").upper()

    # Select which kinases to plot.
    if family and family.upper() != "ALL":
        rows = [
            r for r in rows
            if kinase_families.family_of(r["kinase"]) == family
            or (r["kinase"] or "").upper() == target_u
        ]

    # Drop rows without a value, then sort most cross-reactive first.
    pts = [(r["kinase"], r["avg_iptm"]) for r in rows if r.get("avg_iptm") is not None]
    pts.sort(key=lambda kv: kv[1], reverse=True)

    scope = "all kinases" if not family or family.upper() == "ALL" else f"{family} family"
    fig, ax = plt.subplots(figsize=(max(6, len(pts) * 0.55), 5))

    if not pts:
        ax.text(0.5, 0.5, "No selectivity data for this selection",
                ha="center", va="center", fontsize=12, color="gray")
        ax.axis("off")
    else:
        labels = [k for k, _ in pts]
        values = [v for _, v in pts]
        # Highlight the target kinase's bar.
        colors = ["crimson" if lbl.upper() == target_u else "steelblue" for lbl in labels]
        ax.bar(labels, values, color=colors)

        ax.set_ylabel("Average ipTM", fontsize=12)
        ax.set_xlabel("Kinase", fontsize=12)
        ax.set_title(f"{target_name} binder — average ipTM ({scope})", fontsize=13)
        ax.set_ylim(0, 1)

        ax.axhspan(0.8, 1.0, color="green", alpha=0.08)
        ax.axhspan(0.6, 0.8, color="gray", alpha=0.08)
        ax.axhspan(0.0, 0.6, color="red", alpha=0.08)
        ax.axhline(0.8, color="green", linestyle="--", linewidth=1)
        ax.axhline(0.6, color="red", linestyle="--", linewidth=1)

        plt.xticks(rotation=45, ha="right", fontsize=9)

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()
