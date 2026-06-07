"""Claim record schema definition.

This module defines the structure of a UI claim record used throughout the
prototype. The schema is intentionally explicit about which fields cross
state boundaries and which remain local.

See SCOPE.md for the full privacy architecture rationale.
"""

from dataclasses import dataclass, asdict
from typing import Literal


# Field categories for clarity and downstream tooling
STICKY_HASHED_FIELDS = (
    "claimant_ssn",
    "device_fingerprint",
    "bank_routing",
    "bank_account",
)

QUASI_IDENTIFIER_FIELDS = (
    "first_name",
    "last_name",
    "dob",
    "address",
    "ip_address",
)

CROSS_STATE_CONTEXT_FIELDS = (
    "claim_id",
    "filing_state",
    "claim_date",
    "weekly_benefit_amount",
    "employer_ein",
)

ALL_FIELDS = (
    CROSS_STATE_CONTEXT_FIELDS
    + STICKY_HASHED_FIELDS
    + QUASI_IDENTIFIER_FIELDS
)


@dataclass
class Claim:
    """A single UI claim record.

    Fields are grouped by their privacy classification. See module-level
    constants for the canonical categorization.
    """

    # Cross-state context (plain text in federation exchange)
    claim_id: str
    filing_state: Literal["AA", "BB"]
    claim_date: str  # YYYY-MM-DD
    weekly_benefit_amount: int
    employer_ein: str

    # Sticky identifiers (hashed before federation exchange)
    claimant_ssn: str
    device_fingerprint: str
    bank_routing: str
    bank_account: str

    # Quasi-identifiers (local-only, retrieved via audited per-claim lookup)
    first_name: str
    last_name: str
    dob: str  # YYYY-MM-DD
    address: str
    ip_address: str

    def to_dict(self) -> dict:
        return asdict(self)