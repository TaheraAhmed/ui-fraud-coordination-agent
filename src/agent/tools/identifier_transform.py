"""Cryptographic transformation of sensitive identifiers for federation exchange.

Implements the privacy-preserving identifier protocol: sensitive identifiers
(SSN, device fingerprint, bank routing, bank account) are transformed using
HMAC-SHA256 under a federation-wide salt before any cross-state exchange.

Properties of HMAC-SHA256 under a shared salt:
- Deterministic: same input + same salt -> same output (enables matching)
- Pre-image resistant: the original value cannot be recovered from the hash
- Collision resistant: distinct inputs are extremely unlikely to share an output
- Salted: a hash from federation X does not match a hash from federation Y

The salt is loaded from the FEDERATION_SALT environment variable. In production
deployment, the salt would be distributed via a secure key management system
(Google Cloud KMS, AWS KMS, or equivalent) and rotated periodically. See
SCOPE.md for the full key management treatment.
"""

import hashlib
import hmac
import os
from typing import Final


# Canonical names of the fields that get transformed before federation exchange
STICKY_HASHED_FIELDS: Final[tuple[str, ...]] = (
    "claimant_ssn",
    "device_fingerprint",
    "bank_routing",
    "bank_account",
)


def _get_salt() -> bytes:
    """Load the federation salt from environment, validating it's set."""
    salt_hex = os.environ.get("FEDERATION_SALT")
    if not salt_hex:
        raise RuntimeError(
            "FEDERATION_SALT environment variable is not set. "
            "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
        )
    try:
        return bytes.fromhex(salt_hex)
    except ValueError as e:
        raise RuntimeError(
            f"FEDERATION_SALT must be a hex string, got: {salt_hex[:20]}..."
        ) from e


def transform_identifier(value: str) -> str:
    """Transform a single identifier via HMAC-SHA256 under the federation salt.

    Returns a 64-character hex digest. The original value is not recoverable
    from the digest.

    Inputs are normalized (stripped of whitespace) before hashing to ensure
    canonical form. This means '123-45-6789' and '123-45-6789 ' produce the
    same digest, but '123456789' (no dashes) does not.
    """
    if value is None:
        raise ValueError("Cannot transform a None value")
    normalized = str(value).strip()
    if not normalized:
        raise ValueError("Cannot transform an empty value")

    salt = _get_salt()
    digest = hmac.new(
        key=salt,
        msg=normalized.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return digest


def transform_claim_identifiers(claim: dict) -> dict:
    """Return a copy of the claim with sticky identifiers replaced by hashes.

    The returned dict has the same shape as the input but with sensitive
    identifier fields replaced by their HMAC-SHA256 digests.

    Non-sticky fields are passed through unchanged. Quasi-identifier fields
    (first_name, last_name, dob, address, ip_address) are NOT included in
    the returned dict at all — they are stripped, enforcing the architectural
    rule that quasi-identifiers never appear in federation-exchange records.

    To retrieve quasi-identifiers for a specific claim, use the audited
    per-claim lookup tool (request_local_details), which writes an audit
    log entry for every request.
    """
    from src.data.schema import (
        CROSS_STATE_CONTEXT_FIELDS,
        STICKY_HASHED_FIELDS as SCHEMA_STICKY_FIELDS,
        QUASI_IDENTIFIER_FIELDS,
    )

    # Sanity check: the schema and the transform module must agree on which
    # fields are sticky. This guards against drift.
    assert set(SCHEMA_STICKY_FIELDS) == set(STICKY_HASHED_FIELDS), (
        "Schema and identifier_transform module disagree on STICKY_HASHED_FIELDS"
    )

    federated_record = {}

    # Pass through cross-state context fields unchanged
    for field in CROSS_STATE_CONTEXT_FIELDS:
        federated_record[field] = claim[field]

    # Hash sticky identifiers
    for field in STICKY_HASHED_FIELDS:
        federated_record[f"{field}_hash"] = transform_identifier(claim[field])

    # Quasi-identifiers are intentionally NOT included
    # (architectural enforcement of the privacy boundary)

    return federated_record