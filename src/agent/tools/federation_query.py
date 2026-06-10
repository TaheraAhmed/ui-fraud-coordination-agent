"""Federation query tool: search both simulated states for hash matches.

Given a hashed identifier and the type it represents, this tool queries both
the legacy state (EBCDIC file via legacy reader) and the modernized state
(MongoDB via modern reader) for matching claims. It returns matches in
federation-safe form (no quasi-identifiers) and writes an audit log entry
for every query.

This is the tool that operationalizes cross-state fraud detection: a State A
claim's hashed SSN can be queried against State B without raw SSN ever
crossing the boundary. The audit trail captures every such query.
"""

import os
from typing import Optional

from dotenv import load_dotenv
from pymongo import MongoClient

from src.agent.tools.audit import write_audit_event
from src.agent.tools.identifier_transform import STICKY_HASHED_FIELDS
from src.agent.tools.legacy_reader import read_legacy_source
from src.agent.tools.modern_reader import search_modern_source_by_hash


load_dotenv()


DATABASE_NAME = "ui_fraud_coordination"
FEDERATION_MATCHES_COLLECTION = "federation_matches"


# Cache the legacy state read because re-reading the EBCDIC file on every
# query is expensive and unnecessary — the file doesn't change during a session.
_legacy_records_cache: Optional[list[dict]] = None


def _get_legacy_records() -> list[dict]:
    """Read State A's full federation-safe record set, cached after first call."""
    global _legacy_records_cache
    if _legacy_records_cache is None:
        _legacy_records_cache = read_legacy_source()
    return _legacy_records_cache


def _search_legacy_by_hash(identifier_type: str, hash_value: str) -> list[dict]:
    """Filter cached legacy records by hash field."""
    records = _get_legacy_records()
    return [r for r in records if r.get(identifier_type) == hash_value]


_mongo_client: MongoClient | None = None


def _get_federation_matches_collection():
    global _mongo_client
    if _mongo_client is None:
        uri = os.environ.get("MONGODB_URI")
        _mongo_client = MongoClient(uri)
    return _mongo_client[DATABASE_NAME][FEDERATION_MATCHES_COLLECTION]


def query_federation(
    identifier_type: str,
    hash_value: str,
    requesting_investigator: str,
) -> dict:
    """Search both simulated states for claims matching a hashed identifier.

    Args:
        identifier_type: One of "claimant_ssn_hash", "device_fingerprint_hash",
            "bank_routing_hash", "bank_account_hash".
        hash_value: 64-character hex digest to search for.
        requesting_investigator: Identity of the investigator initiating the query.

    Returns:
        A dict with the query result:
            {
                "identifier_type": str,
                "hash_value": str,
                "matches_state_a": list[dict],   # federation-safe claims
                "matches_state_b": list[dict],   # federation-safe claims
                "total_matches": int,
                "is_cross_state": bool,           # True if matches in both states
                "audit_event_hash": str,          # links to the audit log entry
            }
    """
    valid_types = {f"{field}_hash" for field in STICKY_HASHED_FIELDS}
    if identifier_type not in valid_types:
        raise ValueError(
            f"identifier_type must be one of {sorted(valid_types)}, "
            f"got {identifier_type!r}"
        )
    if len(hash_value) != 64:
        raise ValueError(
            f"hash_value must be a 64-character hex digest, got length {len(hash_value)}"
        )

    # Query both states
    matches_a = _search_legacy_by_hash(identifier_type, hash_value)
    matches_b = search_modern_source_by_hash(identifier_type, hash_value)

    total = len(matches_a) + len(matches_b)
    is_cross_state = len(matches_a) > 0 and len(matches_b) > 0

    # Write audit log entry for the federation query
    audit_event = write_audit_event(
        event_type="federation_query",
        requesting_investigator=requesting_investigator,
        details={
            "identifier_type": identifier_type,
            "hash_value": hash_value,
            "matches_in_state_a": len(matches_a),
            "matches_in_state_b": len(matches_b),
            "is_cross_state": is_cross_state,
        },
    )

    # Persist any matches into the federation_matches working collection.
    # This builds up the agent's cross-source graph over the investigation.
    if total > 0:
        all_match_claim_ids = (
            [c["claim_id"] for c in matches_a]
            + [c["claim_id"] for c in matches_b]
        )
        _get_federation_matches_collection().insert_one({
            "identifier_type": identifier_type,
            "hash_value": hash_value,
            "matched_claim_ids": all_match_claim_ids,
            "queried_at": audit_event["timestamp"],
            "requesting_investigator": requesting_investigator,
            "audit_event_hash": audit_event["event_hash"],
        })

    return {
        "identifier_type": identifier_type,
        "hash_value": hash_value,
        "matches_state_a": matches_a,
        "matches_state_b": matches_b,
        "total_matches": total,
        "is_cross_state": is_cross_state,
        "audit_event_hash": audit_event["event_hash"],
    }


if __name__ == "__main__":
    # Demo: query a seeded SSN-reuse pair end-to-end
    import json
    from src.agent.tools.identifier_transform import transform_identifier

    with open("data/ground_truth.json") as f:
        ground_truth = json.load(f)

    pair = ground_truth["pattern_1_ssn_reuse"][0]
    shared_ssn = pair["shared_ssn_hash_input"]
    target_hash = transform_identifier(shared_ssn)

    print(f"Querying federation for SSN hash: {target_hash[:16]}...\n")

    result = query_federation(
        identifier_type="claimant_ssn_hash",
        hash_value=target_hash,
        requesting_investigator="demo_investigator",
    )

    print(f"Total matches: {result['total_matches']}")
    print(f"Cross-state: {result['is_cross_state']}")
    print(f"State A matches: {[m['claim_id'] for m in result['matches_state_a']]}")
    print(f"State B matches: {[m['claim_id'] for m in result['matches_state_b']]}")
    print(f"Audit event hash: {result['audit_event_hash'][:16]}...")