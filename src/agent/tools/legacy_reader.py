"""Read EBCDIC fixed-width records from a legacy state UI system export.

This tool is the agent's interface to a state UI system that still emits data
in COBOL copybook-defined fixed-width EBCDIC binary records — the format the
majority of US state UI mainframes still use today (GAO-23-105478).

The tool encapsulates three operations:
1. Reading the binary file in fixed-record-length chunks
2. Decoding EBCDIC bytes to UTF-8 strings and splitting by copybook offsets
3. Transforming sticky identifiers via HMAC-SHA256 before returning

The output is in the federation-exchange shape: cross-state context fields
in plain text, sticky identifiers replaced by `_hash` suffixed digests, and
quasi-identifier fields stripped entirely.

To retrieve quasi-identifiers for a specific claim, use the audited per-claim
lookup tool (request_local_details) — which will be implemented on Day 3.
"""

import json
from pathlib import Path

from src.agent.tools.identifier_transform import transform_claim_identifiers
from src.data.copybook_parser import RecordSpec, parse_copybook


# Default paths — overrideable per call for testing
DEFAULT_COPYBOOK_PATH = Path("src/data/copybook_layout.txt")
DEFAULT_LEGACY_FILE_PATH = Path("data/state_a_legacy.dat")

EBCDIC_CODEC = "cp037"


def _decode_record(raw_bytes: bytes, spec: RecordSpec) -> dict:
    """Decode a single EBCDIC binary record into a plain-text claim dict.
    
    Returns the raw claim with all 14 fields. The caller is responsible
    for applying transform_claim_identifiers before any federation exchange.
    """
    if len(raw_bytes) != spec.total_length:
        raise ValueError(
            f"Record length mismatch: expected {spec.total_length} bytes, "
            f"got {len(raw_bytes)} bytes"
        )

    decoded = raw_bytes.decode(EBCDIC_CODEC)
    claim = {}
    for field in spec.fields:
        raw_value = decoded[field.offset:field.offset + field.length]
        # PIC X (alphanumeric) fields are space-padded on the right — strip
        # PIC 9 (numeric) fields are zero-padded on the left — convert to int
        if field.pic_type == "9":
            claim[field.python_name] = int(raw_value)
        else:
            claim[field.python_name] = raw_value.rstrip()
    return claim


def read_legacy_source(
    file_path: str | Path = DEFAULT_LEGACY_FILE_PATH,
    copybook_path: str | Path = DEFAULT_COPYBOOK_PATH,
    max_records: int | None = None,
) -> list[dict]:
    """Read claim records from an EBCDIC fixed-width legacy data file.
    
    Args:
        file_path: Path to the EBCDIC binary file.
        copybook_path: Path to the COBOL copybook layout file.
        max_records: Optional cap on records to return. If None, reads all.
    
    Returns:
        List of federated-shape claim records, with sticky identifiers
        transformed to HMAC-SHA256 digests and quasi-identifiers removed.
        These records are safe to exchange across state boundaries.
    
    Raises:
        FileNotFoundError: if either path doesn't exist
        ValueError: if the file size is not a multiple of the record length
    """
    file_path = Path(file_path)
    copybook_path = Path(copybook_path)

    spec = parse_copybook(copybook_path)
    file_size = file_path.stat().st_size

    if file_size % spec.total_length != 0:
        raise ValueError(
            f"File size {file_size} is not a multiple of record length "
            f"{spec.total_length}. The file may be corrupted or the copybook "
            f"may not match the file format."
        )

    total_records = file_size // spec.total_length
    records_to_read = total_records if max_records is None else min(max_records, total_records)

    federated_records = []
    with file_path.open("rb") as f:
        for _ in range(records_to_read):
            raw = f.read(spec.total_length)
            raw_claim = _decode_record(raw, spec)
            federated_claim = transform_claim_identifiers(raw_claim)
            federated_records.append(federated_claim)

    return federated_records


if __name__ == "__main__":
     # Load .env so FEDERATION_SALT is available when running this module directly
    from dotenv import load_dotenv
    load_dotenv()
    # Demo: read first 3 records from the sample file
    records = read_legacy_source(
        file_path="data/samples/state_a_legacy_sample.dat",
        max_records=3,
    )
    print(f"Read {len(records)} federated records from legacy source:\n")
    for i, r in enumerate(records, 1):
        print(f"--- Record {i} ---")
        for k, v in r.items():
            # Truncate hashes for readability in demo output
            display_v = f"{v[:16]}..." if isinstance(v, str) and len(v) == 64 else v
            print(f"  {k:<35} = {display_v}")
        print()