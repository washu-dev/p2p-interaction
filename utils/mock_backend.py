"""Deterministic mock backend functions for the prototype."""

from __future__ import annotations

import hashlib
import random
from typing import Any


AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"


def _seed_from_text(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], 16)


def predict_structures(targets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return reproducible mock ColabFold/AlphaFold2 predictions."""
    predictions: dict[str, dict[str, Any]] = {}
    for target in targets:
        rng = random.Random(_seed_from_text(target["id"]))
        predictions[target["id"]] = {
            "target_id": target["id"],
            "pdb_filename": f'{target["id"]}_predicted.pdb',
            "mean_plddt": round(rng.uniform(78.0, 94.0), 1),
            "status": "Complete",
        }
    return predictions


def generate_binder_designs(
    positive_targets: list[dict[str, Any]],
    negative_targets: list[dict[str, Any]],
    binder_length_min: int,
    binder_length_max: int,
    number_of_designs: int,
    hotspot_residues: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Generate reproducible mock BindCraft/ProteinMPNN binder sequences."""
    target_signature = ",".join(target["id"] for target in positive_targets)
    rng = random.Random(
        _seed_from_text(
            f"{target_signature}|{binder_length_min}|{binder_length_max}|"
            f"{number_of_designs}|{hotspot_residues}"
        )
    )
    designs: list[dict[str, Any]] = []
    for index in range(number_of_designs):
        length = rng.randint(binder_length_min, binder_length_max)
        sequence = "".join(rng.choice(AMINO_ACIDS) for _ in range(length))
        designs.append(
            {
                "binder_id": f"BND-{index + 1:03d}",
                "sequence": sequence,
                "length": length,
            }
        )

    settings = {
        "positive_targets": [target["id"] for target in positive_targets],
        "negative_targets": [target["id"] for target in negative_targets],
        "binder_length_min": binder_length_min,
        "binder_length_max": binder_length_max,
        "number_of_designs": number_of_designs,
        "target_hotspot_residues": hotspot_residues or None,
        "backend": "BindCraft + ProteinMPNN + AlphaFold2 validation (mock)",
    }
    return designs, settings
