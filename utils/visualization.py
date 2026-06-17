"""Visualization helpers for binder screening results."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go


def create_interaction_heatmap(
    score_matrix: pd.DataFrame,
    positive_target_ids: list[str],
    negative_target_ids: list[str],
) -> go.Figure:
    """Build a heatmap with clearly labeled positive and negative targets."""
    display_labels = [
        f"Positive | {target_id}" for target_id in positive_target_ids
    ] + [f"Negative | {target_id}" for target_id in negative_target_ids]

    figure = go.Figure(
        data=go.Heatmap(
            z=score_matrix.values,
            x=display_labels,
            y=score_matrix.index.tolist(),
            zmin=0,
            zmax=1,
            colorscale=[
                [0.0, "#f5f3ff"],
                [0.35, "#c4b5fd"],
                [0.7, "#60a5fa"],
                [1.0, "#1d4ed8"],
            ],
            colorbar={"title": "Binding<br>score"},
            hovertemplate=(
                "Binder: %{y}<br>Target: %{x}<br>Score: %{z:.3f}<extra></extra>"
            ),
        )
    )

    positive_count = len(positive_target_ids)
    if positive_count:
        figure.add_vrect(
            x0=-0.5,
            x1=positive_count - 0.5,
            fillcolor="#2563eb",
            opacity=0.06,
            line_width=2,
            line_color="#2563eb",
        )
    if negative_target_ids:
        figure.add_vrect(
            x0=positive_count - 0.5,
            x1=len(display_labels) - 0.5,
            fillcolor="#7c3aed",
            opacity=0.06,
            line_width=2,
            line_color="#7c3aed",
        )

    figure.update_layout(
        height=max(430, 34 * len(score_matrix.index) + 180),
        margin={"l": 20, "r": 20, "t": 45, "b": 90},
        xaxis_title="Targets",
        yaxis_title="Designed binders",
        xaxis={"tickangle": -35, "side": "bottom"},
        template="plotly_white",
    )
    return figure
