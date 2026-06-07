"""Write claim records to fixed-width EBCDIC binary format.

EBCDIC (Extended Binary Coded Decimal Interchange Code) is the character
encoding used by IBM mainframes since the 1960s. The majority of state
unemployment insurance systems still emit data in EBCDIC fixed-width records
following COBOL copybook layouts.

This module converts our JSON claim data into that legacy format, producing
binary files that are byte-for-byte representative of what a real state UI
mainframe would export.

Codepage cp037 is the standard EBCDIC variant used in US mainframe systems.
"""

import json
from pathlib import Path

from src.data.copybook_parser import RecordSpec, parse_copybook


# Standard US EBCDIC codepage. Other variants exist (cp500, cp1140) for
# European and international mainframes, but cp037 is the dominant US choice.
EBCDIC_CODEC = "cp037"

DATA_DIR = Path("data")
SAMPLES_DIR = DATA_DIR / "samples"
COPYBOOK_PATH = Path("src/data/copybook_layout.txt")

STATE_A_JSON_PATH = DATA_DIR / "state_a_claims.json"
STATE_A_LEGACY_PATH = DATA_DIR / "state_a_legacy.dat"
STATE_A_LEGACY_SAMPLE_PATH = SAMPLES_DIR / "state_a_legacy_sample.dat"

SAMPLE_RECORD_COUNT = 20


def format_field(value, length: int, pic_type: str) -> str:
    """Format a single field value to fixed width per copybook spec.
    
    PIC X fields are left-justified, space-padded.
    PIC 9 fields are right-justified, zero-padded.
    """
    s = str(value)
    if len(s) > length:
        # Truncate if too long. In a real system this should be an error,
        # but our generator already enforces lengths so this is defensive.
        s = s[:length]
    if pic_type == "9":
        return s.rjust(length, "0")
    else:  # X
        return s.ljust(length, " ")


def claim_to_record_bytes(claim: dict, spec: RecordSpec) -> bytes:
    """Convert a single claim dict into a fixed-width EBCDIC byte record."""
    parts: list[str] = []
    for field in spec.fields:
        raw_value = claim[field.python_name]
        formatted = format_field(raw_value, field.length, field.pic_type)
        parts.append(formatted)
    ascii_record = "".join(parts)
    assert len(ascii_record) == spec.total_length, (
        f"Record length mismatch: got {len(ascii_record)}, expected {spec.total_length}"
    )
    return ascii_record.encode(EBCDIC_CODEC)


def write_legacy_file(claims: list[dict], path: Path, spec: RecordSpec) -> None:
    """Write a list of claims to a fixed-width EBCDIC binary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        for claim in claims:
            f.write(claim_to_record_bytes(claim, spec))


def main():
    
    spec = parse_copybook(COPYBOOK_PATH)

    with STATE_A_JSON_PATH.open() as f:
        claims_a = json.load(f)

    # Write the full legacy file (gitignored)
    write_legacy_file(claims_a, STATE_A_LEGACY_PATH, spec)
    print(f"Wrote {len(claims_a)} records ({len(claims_a) * spec.total_length} bytes) -> {STATE_A_LEGACY_PATH}")

    # Write a small committed sample
    sample = claims_a[:SAMPLE_RECORD_COUNT]
    write_legacy_file(sample, STATE_A_LEGACY_SAMPLE_PATH, spec)
    print(f"Wrote {len(sample)} sample records -> {STATE_A_LEGACY_SAMPLE_PATH}")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    main()