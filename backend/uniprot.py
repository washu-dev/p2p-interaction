"""UniProt REST client — ports the search -> select -> download logic from
../fetch_uniprot/fetch_uniprot.sh so kinase sequences can be found and pulled
straight from the web UI instead of the command line.

UniProt returns TSV columns in the same order the `fields` param was given in,
regardless of the (human-readable) header text — so we index columns
positionally, exactly like the awk in fetch_uniprot.sh does.
"""
from __future__ import annotations

import csv
import io

import httpx

API = "https://rest.uniprot.org/uniprotkb"
FIELDS = "accession,id,reviewed,protein_name,gene_names,organism_name,length,ft_domain"
_COLS = ["accession", "entry_id", "reviewed", "protein_name", "gene_names", "organism", "length", "domains"]
_HEADERS = {"User-Agent": "bindcraft-gui/1.0"}


class UniprotError(Exception):
    pass


def _get(url: str, params: dict | None = None) -> bytes:
    try:
        r = httpx.get(url, params=params, headers=_HEADERS, timeout=30)
        r.raise_for_status()
        return r.content
    except httpx.HTTPError as e:
        raise UniprotError(f"could not reach UniProt: {e}") from e


def make_search_query(protein: str, organism: str) -> str:
    q = f"({protein})"
    if organism:
        q += f' AND (organism_name:"{organism}")'
    return q


def search(protein: str, organism: str = "Homo sapiens", size: int = 5) -> list[dict]:
    """Search UniProtKB for a gene/protein name; returns candidate rows, best first."""
    params = {
        "query": make_search_query(protein, organism),
        "fields": FIELDS,
        "format": "tsv",
        "size": str(size),
    }
    text = _get(f"{API}/search", params=params).decode("utf-8", errors="replace")
    rows = list(csv.reader(io.StringIO(text), delimiter="\t"))[1:]  # skip header row
    candidates = [dict(zip(_COLS, r + [""] * (len(_COLS) - len(r)), strict=False)) for r in rows if r]
    for c in candidates:
        c["reviewed"] = c["reviewed"].strip().lower() == "reviewed"
    # Reviewed (Swiss-Prot) entries first, preserving UniProt's own relevance order otherwise.
    candidates.sort(key=lambda c: 0 if c["reviewed"] else 1)
    return candidates


def fetch_fasta(accession: str) -> str:
    """Download the FASTA record for a UniProt accession (e.g. O95835)."""
    if not accession or not accession.replace("-", "").isalnum():
        raise UniprotError(f"invalid accession: {accession!r}")
    return _get(f"{API}/{accession}.fasta").decode("utf-8", errors="replace")
