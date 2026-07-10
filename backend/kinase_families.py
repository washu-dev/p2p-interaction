"""Manning kinome-group classification for the selectivity panel.

Maps each kinase in the panel to one of the eight canonical Manning groups
(AGC, CAMK, CK1, CMGC, STE, TK, TKL, Other). Used by the binder library to let a
user view a binder's selectivity against just one family of kinases.

Lookups are case-insensitive; anything not listed falls back to "Other".
Common aliases are included (e.g. NDR1=STK38, MST1=STK4, MST2=STK3) so names
coming from either the sample panel or the cluster CSV both resolve.
"""
from __future__ import annotations

# Group order is the conventional display order.
GROUP_ORDER = ["AGC", "CAMK", "CK1", "CMGC", "STE", "TK", "TKL", "Other"]

# kinase (upper-case) -> Manning group. Curated for the ~63-kinase panel.
_MEMBERS: dict[str, list[str]] = {
    "AGC": [
        "AKT1", "GRK2", "PRKACA", "PRKCA", "PRKCZ", "PDPK1", "ROCK1", "ROCK2",
        "RPS6KA1", "RPS6KB1", "SGK1",
        # NDR/LATS subfamily (STK38/STK38L aliases included)
        "NDR1", "NDR2", "STK38", "STK38L", "LATS1", "LATS2",
    ],
    "CAMK": [
        "CAMK2A", "CAMK4", "CHEK1", "CHEK2", "DAPK1", "MARK2", "MELK",
        "STK17A", "STK17B",
    ],
    "CK1": ["CSNK1A1", "CSNK1D", "CSNK1E", "VRK1"],
    "CMGC": [
        "CDK1", "CDK2", "CDK4", "CDK7", "CDK9", "MAPK1", "MAPK14", "MAPK8",
        "GSK3B", "CLK1", "DYRK1A", "SRPK1",
    ],
    "STE": [
        "MAP2K1", "MAP3K5", "MAP4K4", "STK24",
        # MST family (STK3=MST2, STK4=MST1)
        "STK3", "STK4", "MST1", "MST2",
    ],
    "TK": ["ABL1", "ALK", "EGFR", "ERBB2", "FGFR1", "JAK2", "KDR", "MET", "RET", "SRC", "ZAP70"],
    "TKL": ["BRAF", "RAF1", "IRAK4", "RIPK1"],
    # Atypical PIKK kinases + the non-kinase example target (PDL1).
    "Other": ["ATM", "ATR", "MTOR", "PRKDC", "PDL1"],
}

# Flattened reverse index, upper-cased for case-insensitive lookup.
FAMILY_OF: dict[str, str] = {
    k.upper(): group for group, members in _MEMBERS.items() for k in members
}


def family_of(kinase: str) -> str:
    """Manning group for a kinase name (case-insensitive); 'Other' if unknown."""
    return FAMILY_OF.get((kinase or "").upper(), "Other")


def groups() -> list[str]:
    """All group names in display order."""
    return list(GROUP_ORDER)


def kinases_in(group: str) -> list[str]:
    """Canonical member names of a group (empty if the group is unknown)."""
    return list(_MEMBERS.get(group, []))
