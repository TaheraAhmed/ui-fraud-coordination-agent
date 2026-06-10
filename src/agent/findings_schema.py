"""Schema for the agent's structured findings output.

The agent's response is split into two parts:
  - A structured findings object (machine-readable, for evaluation and audit)
  - A markdown narrative (human-readable, for the investigator UI)

The structured findings make the agent's conclusions explicit and unambiguous,
removing the need to heuristically parse markdown to determine what the agent
concluded. This is the foundation for the evaluation suite and for any
downstream system that needs to act on the agent's findings programmatically.
"""

from typing import Literal, TypedDict


PrimaryOutcome = Literal["cross_state", "within_state_only", "no_match"]
HashFieldName = Literal[
    "claimant_ssn_hash",
    "device_fingerprint_hash",
    "bank_routing_hash",
    "bank_account_hash",
]


class HashMatches(TypedDict, total=False):
    """Claim IDs matched on a specific hash field, separated by location."""
    claimant_ssn_hash: list[str]
    device_fingerprint_hash: list[str]
    bank_routing_hash: list[str]
    bank_account_hash: list[str]


class StructuredFindings(TypedDict):
    """The machine-readable findings the agent produces for every investigation."""

    source_claim_id: str
    primary_outcome: PrimaryOutcome
    cross_state_matches: HashMatches
    within_state_matches: HashMatches
    audit_event_hashes: list[str]


# The JSON Schema Gemini will be instructed to produce. Kept as a plain dict
# (not a Python type) because that's what we pass to the model's structured-
# output config.
GEMINI_FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "source_claim_id": {
            "type": "string",
            "description": "The claim ID under investigation, e.g. 'SA-000001126'.",
        },
        "primary_outcome": {
            "type": "string",
            "enum": ["cross_state", "within_state_only", "no_match"],
            "description": (
                "The classified outcome of the investigation. "
                "'cross_state' means at least one hash matched a claim in the OTHER state. "
                "'within_state_only' means the only meaningful matches are claims in the SAME state. "
                "'no_match' means no meaningful matches beyond the source claim's self-match."
            ),
        },
        "cross_state_matches": {
            "type": "object",
            "description": "Claim IDs in the OTHER state matched by each hash field. Empty arrays where no match.",
            "properties": {
                "claimant_ssn_hash": {"type": "array", "items": {"type": "string"}},
                "device_fingerprint_hash": {"type": "array", "items": {"type": "string"}},
                "bank_routing_hash": {"type": "array", "items": {"type": "string"}},
                "bank_account_hash": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "claimant_ssn_hash",
                "device_fingerprint_hash",
                "bank_routing_hash",
                "bank_account_hash",
            ],
        },
        "within_state_matches": {
            "type": "object",
            "description": "Claim IDs in the SAME state matched by each hash field (excluding the source claim itself). Empty arrays where no match.",
            "properties": {
                "claimant_ssn_hash": {"type": "array", "items": {"type": "string"}},
                "device_fingerprint_hash": {"type": "array", "items": {"type": "string"}},
                "bank_routing_hash": {"type": "array", "items": {"type": "string"}},
                "bank_account_hash": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "claimant_ssn_hash",
                "device_fingerprint_hash",
                "bank_routing_hash",
                "bank_account_hash",
            ],
        },
        "audit_event_hashes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "All audit event hashes generated during this investigation.",
        },
        "narrative": {
            "type": "string",
            "description": (
                "The human-readable due-process explanation in markdown, following the "
                "Output Format For Findings section of the system prompt. This is what "
                "the investigator UI displays. Distinguish primary cross-state findings "
                "from secondary within-state findings, cite audit hashes, and be honest "
                "about what the evidence supports."
            ),
        },
    },
    "required": [
        "source_claim_id",
        "primary_outcome",
        "cross_state_matches",
        "within_state_matches",
        "audit_event_hashes",
        "narrative",
    ],
}