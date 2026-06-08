"""Audited per-claim lookup of quasi-identifiers.

When a federation query surfaces a cross-state hash match, the next question
is usually "who is this claim associated with?" The answer requires releasing
quasi-identifying fields (name, DOB, address, IP) that are otherwise kept
strictly local to each state.

This tool is the audited release mechanism. Every call:
  1. Requires the caller to specify which claim and why
  2. Returns ONLY the quasi-identifier fields, never the sticky identifiers
  3. Writes an audit log entry capturing the requesting investigator, the
     specific fields released, and the stated justification

This implements the "request-and-release" privacy pattern: information is not
broadly shared, but specifically requested and logged per use. The methodology
paper presents this alongside the cryptographic transformation as the two
distinct privacy primitives of the system.
"""

import json
import os
from pathlib import Path
from typing import Final

from dotenv import load_dotenv
from pymongo import MongoClient

from src.agent.tools.audit import write_audit_event


load_dotenv()


DATABASE_NAME = "ui_fraud_coordination"
STATE_B_COLLECTION = "state_b_claims"

# Quasi-identifier fields that this tool may release.
# These are exactly the five fields excluded from federation-exchange records.
QUASI_IDENTIFIER_FIELDS: Final[tuple[str, ...]] = (
    "first_name",
    "last_name",
    "dob",
    "address",
    "ip_address",
)


def _get_state_b_collection():
    uri = os.environ.get("MONGODB_URI")
    client = MongoClient(uri)
    return client[DATABASE_NAME][STATE_B_COLLECTION]


def _lookup_state_a_claim(claim_id: str) -> dict | None:
    """Find a State A claim by ID in the source JSON (raw representation)."""
    state_a_path = Path("data/state_a_claims.json")
    with state_a_path.open() as f:
        claims = json.load(f)
    for claim in claims:
        if claim["claim_id"] == claim_id:
            return claim
    return None


def _lookup_state_b_claim(claim_id: str) -> dict | None:
    """Find a State B claim by ID in MongoDB."""
    return _get_state_b_collection().find_one(
        {"claim_id": claim_id},
        projection={"_id": 0},
    )


def request_local_details(
    claim_id: str,
    requesting_investigator: str,
    justification: str,
) -> dict:
    """Request release of quasi-identifier fields for a specific claim.

    This is the only mechanism by which quasi-identifiers (name, DOB, address,
    IP) can be retrieved. Every release is logged with the requesting party
    and stated justification.

    Args:
        claim_id: The claim to look up. Must start with "SA-" or "SB-" to
            indicate which state owns the claim.
        requesting_investigator: Identity of the investigator requesting
            release.
        justification: Why this lookup is needed. Free-form text in the
            prototype; production would require structured justification
            against approved investigation reasons.

    Returns:
        A dict with the released fields and audit metadata:
            {
                "claim_id": str,
                "filing_state": str,
                "released_fields": {first_name, last_name, dob, address, ip_address},
                "audit_event_hash": str,
            }
    """
    if not isinstance(justification, str) or not justification.strip():
        raise ValueError(
            "justification is required and must be a non-empty string. "
            "Quasi-identifier release cannot proceed without a logged reason."
        )

    # Determine source by claim_id prefix
    if claim_id.startswith("SA-"):
        filing_state = "AA"
        claim = _lookup_state_a_claim(claim_id)
    elif claim_id.startswith("SB-"):
        filing_state = "BB"
        claim = _lookup_state_b_claim(claim_id)
    else:
        raise ValueError(
            f"Cannot route lookup for claim_id {claim_id!r}: "
            f"expected prefix 'SA-' or 'SB-'."
        )

    if claim is None:
        # Still write an audit event for the failed lookup. A request that
        # didn't find a record is still a request, and forensically important.
        audit_event = write_audit_event(
            event_type="quasi_identifier_release_failed",
            requesting_investigator=requesting_investigator,
            details={
                "claim_id": claim_id,
                "filing_state": filing_state,
                "justification": justification,
                "reason": "claim_not_found",
            },
        )
        raise LookupError(
            f"No claim found with ID {claim_id!r} in {filing_state}. "
            f"Failed lookup logged with audit hash {audit_event['event_hash'][:16]}..."
        )

    # Extract only the quasi-identifier fields
    released = {field: claim[field] for field in QUASI_IDENTIFIER_FIELDS}

    # Write the release event to the audit log
    audit_event = write_audit_event(
        event_type="quasi_identifier_release",
        requesting_investigator=requesting_investigator,
        details={
            "claim_id": claim_id,
            "filing_state": filing_state,
            "released_fields": list(QUASI_IDENTIFIER_FIELDS),
            "justification": justification,
        },
    )

    return {
        "claim_id": claim_id,
        "filing_state": filing_state,
        "released_fields": released,
        "audit_event_hash": audit_event["event_hash"],
    }


if __name__ == "__main__":
    # Demo: request quasi-identifiers for a claim in each state
    print("--- Lookup State A claim ---")
    result_a = request_local_details(
        claim_id="SA-000000001",
        requesting_investigator="demo_investigator",
        justification="Demo: verifying lookup tool functionality on State A",
    )
    print(f"Filing state: {result_a['filing_state']}")
    print(f"Released: {result_a['released_fields']}")
    print(f"Audit hash: {result_a['audit_event_hash'][:16]}...")

    print("\n--- Lookup State B claim ---")
    result_b = request_local_details(
        claim_id="SB-000000001",
        requesting_investigator="demo_investigator",
        justification="Demo: verifying lookup tool functionality on State B",
    )
    print(f"Filing state: {result_b['filing_state']}")
    print(f"Released: {result_b['released_fields']}")
    print(f"Audit hash: {result_b['audit_event_hash'][:16]}...")