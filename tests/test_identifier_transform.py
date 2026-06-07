"""Tests for the identifier transformation function.

The most important test here is `test_raw_pii_never_appears_in_federated_record`
— it proves the core privacy claim of the system.
"""

import os

import pytest

from src.agent.tools.identifier_transform import (
    transform_identifier,
    transform_claim_identifiers,
    STICKY_HASHED_FIELDS,
)


# Pytest fixture: ensure the salt is set during tests
@pytest.fixture(autouse=True)
def ensure_salt_loaded():
    """The .env file should already be loaded by conftest.py or pytest-dotenv.

    If FEDERATION_SALT is missing, the tests should fail loudly so the
    contributor knows their .env is incomplete.
    """
    if not os.environ.get("FEDERATION_SALT"):
        # Try to load .env manually if dotenv hasn't been loaded
        from dotenv import load_dotenv
        load_dotenv()
    assert os.environ.get("FEDERATION_SALT"), (
        "FEDERATION_SALT must be set in .env for tests to run"
    )


# ---------- Determinism ----------

def test_same_input_same_output():
    """Two transformations of the same value must produce identical hashes.
    
    This is the foundation of cross-state matching: State A and State B
    hashing the same SSN must produce the same digest.
    """
    a = transform_identifier("123-45-6789")
    b = transform_identifier("123-45-6789")
    assert a == b


def test_different_inputs_different_outputs():
    """Different inputs must produce different hashes (no collisions on typical inputs)."""
    a = transform_identifier("123-45-6789")
    b = transform_identifier("987-65-4321")
    assert a != b


def test_whitespace_is_normalized():
    """Leading/trailing whitespace should not change the hash.
    
    Real legacy data may have padding spaces; this prevents two records that
    differ only in padding from producing different hashes.
    """
    a = transform_identifier("123-45-6789")
    b = transform_identifier("  123-45-6789  ")
    assert a == b


# ---------- Output format ----------

def test_output_is_64_hex_chars():
    """SHA-256 produces 256 bits = 32 bytes = 64 hex characters."""
    result = transform_identifier("test-value")
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


# ---------- Error handling ----------

def test_none_input_raises():
    with pytest.raises(ValueError):
        transform_identifier(None)


def test_empty_input_raises():
    with pytest.raises(ValueError):
        transform_identifier("")


def test_whitespace_only_input_raises():
    with pytest.raises(ValueError):
        transform_identifier("   ")


def test_missing_salt_raises(monkeypatch):
    """If FEDERATION_SALT is unset, the function must fail loudly."""
    monkeypatch.delenv("FEDERATION_SALT", raising=False)
    with pytest.raises(RuntimeError, match="FEDERATION_SALT"):
        transform_identifier("any-value")


# ---------- Pre-image resistance (the privacy property) ----------

def test_hash_does_not_contain_input():
    """The hash output must not contain the input as a substring.
    
    A correctly implemented HMAC-SHA256 will never produce a digest containing
    the original input. This is a sanity check, not a cryptographic proof —
    that comes from the algorithm itself.
    """
    sensitive_input = "123-45-6789"
    result = transform_identifier(sensitive_input)
    assert sensitive_input not in result
    assert "123" not in result or len([c for c in result if c == "1"]) < 4
    # The above is a loose check; hex digests will contain digits by chance.


# ---------- The federation record structure ----------

SAMPLE_CLAIM = {
    "claim_id": "SA-000000001",
    "filing_state": "AA",
    "claim_date": "2024-03-15",
    "weekly_benefit_amount": 425,
    "employer_ein": "123456789",
    "claimant_ssn": "555-12-3456",
    "device_fingerprint": "a" * 32,
    "bank_routing": "012345678",
    "bank_account": "987654321012",
    "first_name": "Jane",
    "last_name": "Doe",
    "dob": "1985-06-15",
    "address": "123 Main St",
    "ip_address": "192.168.1.100",
}


def test_federated_record_has_no_quasi_identifiers():
    """The federated record must not contain ANY quasi-identifier field."""
    federated = transform_claim_identifiers(SAMPLE_CLAIM)
    
    forbidden_fields = {"first_name", "last_name", "dob", "address", "ip_address"}
    actual_fields = set(federated.keys())
    overlap = forbidden_fields & actual_fields
    assert not overlap, (
        f"Federated record contains forbidden quasi-identifier fields: {overlap}"
    )


def test_federated_record_has_hashed_sticky_fields():
    """All sticky identifiers must appear in the federated record as *_hash fields."""
    federated = transform_claim_identifiers(SAMPLE_CLAIM)
    
    for field in STICKY_HASHED_FIELDS:
        assert f"{field}_hash" in federated, f"Missing hash for {field}"
        # The raw field must NOT be present
        assert field not in federated, f"Raw {field} leaked into federated record"


def test_federated_record_preserves_context_fields():
    """Cross-state context fields must be present and unchanged."""
    federated = transform_claim_identifiers(SAMPLE_CLAIM)
    
    expected_context = {
        "claim_id": "SA-000000001",
        "filing_state": "AA",
        "claim_date": "2024-03-15",
        "weekly_benefit_amount": 425,
        "employer_ein": "123456789",
    }
    for field, expected_value in expected_context.items():
        assert federated[field] == expected_value


# ---------- THE CRITICAL SECURITY TEST ----------

def test_raw_pii_never_appears_in_federated_record():
    """Comprehensive check that no raw PII value appears anywhere in the federated record.
    
    This is the test the methodology paper cites as evidence of the privacy
    architecture. It exhaustively searches every value in the federated record
    for any raw PII from the original claim.
    """
    federated = transform_claim_identifiers(SAMPLE_CLAIM)
    
    # Collect all values from the federated record as strings
    all_federated_values_str = " ".join(str(v) for v in federated.values())
    
    # The raw values that MUST NOT appear:
    raw_pii_values = [
        SAMPLE_CLAIM["claimant_ssn"],
        SAMPLE_CLAIM["device_fingerprint"],
        SAMPLE_CLAIM["bank_routing"],
        SAMPLE_CLAIM["bank_account"],
        SAMPLE_CLAIM["first_name"],
        SAMPLE_CLAIM["last_name"],
        SAMPLE_CLAIM["dob"],
        SAMPLE_CLAIM["address"],
        SAMPLE_CLAIM["ip_address"],
    ]
    
    for raw_value in raw_pii_values:
        assert raw_value not in all_federated_values_str, (
            f"PRIVACY VIOLATION: Raw value {raw_value!r} appears in federated record. "
            f"This breaks the cross-state privacy guarantee."
        )


def test_two_claims_with_same_ssn_produce_same_hash():
    """Two claims sharing an SSN must produce the same SSN hash.
    
    This is what enables cross-state SSN-reuse detection.
    """
    claim_a = dict(SAMPLE_CLAIM)
    claim_b = dict(SAMPLE_CLAIM)
    claim_b["claim_id"] = "SB-000000001"
    claim_b["filing_state"] = "BB"
    # Same SSN, everything else different
    claim_b["first_name"] = "Different"
    claim_b["last_name"] = "Person"
    claim_b["device_fingerprint"] = "b" * 32
    claim_b["bank_routing"] = "999999999"
    claim_b["bank_account"] = "111111111111"

    fed_a = transform_claim_identifiers(claim_a)
    fed_b = transform_claim_identifiers(claim_b)
    
    assert fed_a["claimant_ssn_hash"] == fed_b["claimant_ssn_hash"]
    # And these should differ
    assert fed_a["device_fingerprint_hash"] != fed_b["device_fingerprint_hash"]