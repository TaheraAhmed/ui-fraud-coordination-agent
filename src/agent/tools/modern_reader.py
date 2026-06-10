"""Read claim records from the modernized state's MongoDB document store.

This is the State B parallel to the State A legacy reader. Both tools produce
federation-safe records in the same shape, demonstrating that the adapter
pattern is genuinely format-agnostic.

Like the legacy reader, this tool returns federation-safe records:
  - Cross-state context fields in plain text
  - Sticky identifiers as HMAC-SHA256 hashes
  - Quasi-identifiers excluded entirely

For quasi-identifiers, callers must use the audited per-claim lookup tool.
"""

import os
from typing import Optional

from dotenv import load_dotenv
from pymongo import MongoClient

from src.agent.tools.identifier_transform import (
    transform_claim_identifiers,
    STICKY_HASHED_FIELDS,
)


load_dotenv()


DATABASE_NAME = "ui_fraud_coordination"
STATE_B_COLLECTION = "state_b_claims"


_mongo_client: MongoClient | None = None


def _get_collection():
    """Return the State B claims collection. Uses a shared client."""
    global _mongo_client
    if _mongo_client is None:
        uri = os.environ.get("MONGODB_URI")
        if not uri:
            raise RuntimeError("MONGODB_URI not set in .env")
        _mongo_client = MongoClient(uri)
    return _mongo_client[DATABASE_NAME][STATE_B_COLLECTION]


def read_modern_source(
    max_records: Optional[int] = None,
    claim_id: Optional[str] = None,
) -> list[dict]:
    """Read federation-safe claim records from the modernized state (MongoDB).

    Args:
        max_records: Optional cap on records to return. If None, reads all.
        claim_id: If provided, returns only the matching claim.

    Returns:
        List of federated-shape claim records with hashed sticky identifiers
        and no quasi-identifiers. Safe for cross-state exchange.
    """
    collection = _get_collection()

    filter_q = {}
    if claim_id is not None:
        filter_q["claim_id"] = claim_id

    cursor = collection.find(filter_q, projection={"_id": 0})
    if max_records is not None:
        cursor = cursor.limit(max_records)

    federated = []
    for doc in cursor:
        # The MongoDB document includes both raw and hash fields — we need to
        # rebuild a clean federation-safe record using transform_claim_identifiers
        # so the privacy boundary is enforced the same way as the legacy reader.
        raw_claim = {k: v for k, v in doc.items() if not k.endswith("_hash")}
        federated_claim = transform_claim_identifiers(raw_claim)
        federated.append(federated_claim)
    return federated


def search_modern_source_by_hash(
    identifier_type: str,
    hash_value: str,
) -> list[dict]:
    """Search State B for claims whose hashed identifier matches.

    Args:
        identifier_type: One of "claimant_ssn_hash", "device_fingerprint_hash",
            "bank_routing_hash", or "bank_account_hash".
        hash_value: 64-character hex digest to match.

    Returns:
        List of matching claims in federation-safe shape.
    """
    valid_types = {f"{field}_hash" for field in STICKY_HASHED_FIELDS}
    if identifier_type not in valid_types:
        raise ValueError(
            f"identifier_type must be one of {sorted(valid_types)}, "
            f"got {identifier_type!r}"
        )
    if len(hash_value) != 64:
        raise ValueError(f"hash_value must be 64 hex chars, got length {len(hash_value)}")

    collection = _get_collection()
    cursor = collection.find({identifier_type: hash_value}, projection={"_id": 0})

    federated = []
    for doc in cursor:
        raw_claim = {k: v for k, v in doc.items() if not k.endswith("_hash")}
        federated_claim = transform_claim_identifiers(raw_claim)
        federated.append(federated_claim)
    return federated


if __name__ == "__main__":
    # Demo: read 3 records and confirm shape matches legacy reader
    records = read_modern_source(max_records=3)
    print(f"Read {len(records)} federated records from modern source:\n")
    for i, r in enumerate(records, 1):
        print(f"--- Record {i} ---")
        for k, v in r.items():
            display_v = f"{v[:16]}..." if isinstance(v, str) and len(v) == 64 else v
            print(f"  {k:<35} = {display_v}")
        print()