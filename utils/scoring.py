"""Mock binder-target scoring and selectivity ranking."""

from __future__ import annotations

import hashlib
import random
from typing import Any

import pandas as pd


def _stable_rng(*parts: str) -> random.Random:
    key = "|".join(parts)
    seed = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:12], 16)
    return random.Random(seed)


def screen_binders(
    binders: list[dict[str, Any]],
    positive_targets: list[dict[str, Any]],
    negative_targets: list[dict[str, Any]],
    pass_threshold: float = 0.35,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create deterministic interaction scores and ranked summary tables."""
    target_columns = [target["id"] for target in positive_targets + negative_targets]
    matrix_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []

    for binder_index, binder in enumerate(binders):
        score_row: dict[str, Any] = {"Binder ID": binder["binder_id"]}
        positive_scores: list[float] = []
        negative_scores: list[float] = []
        weak_design = binder_index % 5 == 4

        for target in positive_targets:
            rng = _stable_rng(binder["binder_id"], target["id"], "positive")
            low, high = (0.55, 0.76) if weak_design else (0.74, 0.97)
            score = round(rng.uniform(low, high), 3)
            positive_scores.append(score)
            score_row[target["id"]] = score

        for target in negative_targets:
            rng = _stable_rng(binder["binder_id"], target["id"], "negative")
            low, high = (0.35, 0.62) if weak_design else (0.08, 0.43)
            score = round(rng.uniform(low, high), 3)
            negative_scores.append(score)
            score_row[target["id"]] = score

        positive_average = sum(positive_scores) / len(positive_scores)
        negative_average = (
            sum(negative_scores) / len(negative_scores) if negative_scores else 0.0
        )
        selectivity_score = positive_average - negative_average
        matrix_rows.append(score_row)
        summary_rows.append(
            {
                "Binder ID": binder["binder_id"],
                "Sequence": binder["sequence"],
                "Positive target score average": round(positive_average, 3),
                "Negative target score average": round(negative_average, 3),
                "Selectivity score": round(selectivity_score, 3),
                "Status": "Pass" if selectivity_score >= pass_threshold else "Fail",
            }
        )

    summary_df = pd.DataFrame(summary_rows).sort_values(
        "Selectivity score", ascending=False
    ).reset_index(drop=True)
    score_matrix_df = pd.DataFrame(matrix_rows).set_index("Binder ID")
    score_matrix_df = score_matrix_df.reindex(
        summary_df["Binder ID"].tolist()
    )[target_columns]
    return summary_df, score_matrix_df
