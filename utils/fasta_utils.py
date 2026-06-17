"""FASTA parsing and validation helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


VALID_AMINO_ACIDS = set("ACDEFGHIKLMNPQRSTVWYBXZJUO")
MAX_SEQUENCE_LENGTH = 5_000
MAX_RECORDS_PER_FILE = 20


def decode_uploaded_file(uploaded_file: Any) -> str:
    """Decode a Streamlit UploadedFile as UTF-8 text."""
    return uploaded_file.getvalue().decode("utf-8-sig").strip()


def validate_fasta(content: str) -> tuple[bool, str]:
    """Perform lightweight validation suitable for the prototype upload UI."""
    stripped = content.strip()
    if not stripped:
        return False, "The file is empty."
    if not stripped.startswith(">"):
        return False, 'FASTA content must start with ">".'

    records = parse_fasta_records(stripped)
    if not records:
        return False, "No FASTA records were found."
    if len(records) > MAX_RECORDS_PER_FILE:
        return False, f"A single file may contain at most {MAX_RECORDS_PER_FILE} records."

    for record in records:
        if not record["sequence"]:
            return False, f'Record "{record["header"]}" has no sequence.'
        if len(record["sequence"]) > MAX_SEQUENCE_LENGTH:
            return False, (
                f'Record "{record["header"]}" exceeds the '
                f"{MAX_SEQUENCE_LENGTH:,}-residue public demo limit."
            )
        invalid = sorted(set(record["sequence"]) - VALID_AMINO_ACIDS)
        if invalid:
            return False, f"Unsupported sequence characters: {', '.join(invalid)}"

    return True, f"{len(records)} FASTA record(s) found."


def parse_fasta_records(content: str) -> list[dict[str, str]]:
    """Parse one or more FASTA records from text."""
    records: list[dict[str, str]] = []
    header: str | None = None
    sequence_parts: list[str] = []

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header is not None:
                records.append(
                    {
                        "header": header,
                        "sequence": "".join(sequence_parts).upper(),
                    }
                )
            header = line[1:].strip() or "unnamed_sequence"
            sequence_parts = []
        elif header is not None:
            sequence_parts.append(re.sub(r"\s+", "", line))

    if header is not None:
        records.append(
            {
                "header": header,
                "sequence": "".join(sequence_parts).upper(),
            }
        )
    return records


def target_id_from_filename(filename: str, record_index: int = 0) -> str:
    """Create a compact, display-safe target identifier."""
    stem = Path(filename).stem
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_") or "target"
    return cleaned if record_index == 0 else f"{cleaned}_{record_index + 1}"


def uploaded_files_to_targets(
    uploaded_files: list[Any] | None, target_type: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Convert uploaded FASTA files into serializable target dictionaries."""
    targets: list[dict[str, Any]] = []
    errors: list[str] = []

    for uploaded_file in uploaded_files or []:
        try:
            content = decode_uploaded_file(uploaded_file)
        except UnicodeDecodeError:
            errors.append(f"{uploaded_file.name}: file is not valid UTF-8 text.")
            continue

        is_valid, message = validate_fasta(content)
        if not is_valid:
            errors.append(f"{uploaded_file.name}: {message}")
            continue

        for index, record in enumerate(parse_fasta_records(content)):
            target_id = target_id_from_filename(uploaded_file.name, index)
            targets.append(
                {
                    "id": target_id,
                    "filename": uploaded_file.name,
                    "header": record["header"],
                    "sequence": record["sequence"],
                    "content": f'>{record["header"]}\n{record["sequence"]}',
                    "type": target_type,
                }
            )

    return targets, errors
