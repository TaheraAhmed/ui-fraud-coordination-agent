"""Tests for the audited per-claim lookup tool."""

import json

import pytest
from dotenv import load_dotenv

load_dotenv()

from src.agent.tools.local_lookup import (
    request_local_details,
    QUASI_IDENTIFIER_FIELDS,
)
from src.agent.tools.audit import list_audit_events


# ---------- Basic lookups ----------

def test_lookup_state_a_claim_returns_quasi_identifiers():
    result = request_local_details(
        claim_id="SA-000000001",
        requesting_investigator="test_user",
        justification="Test: state A lookup",
    )
    assert result["claim_id"] == "SA-000000001"
    assert result["filing_state"] == "AA"
    released = result["released_fields"]
    for field in QUASI_IDENTIFIER_FIELDS:
        assert field in released


def test_lookup_state_b_claim_returns_quasi_identifiers():
    result = request_local_details(
        claim_id="SB-000000001",
        requesting_investigator="test_user",
        justification="Test: state B lookup",
    )
    assert result["claim_id"] == "SB-000000001"
    assert result["filing_state"] == "BB"
    released = result["released_fields"]
    for field in QUASI_IDENTIFIER_FIELDS:
        assert field in released


def test_released_fields_contain_only_quasi_identifiers():
    """The release must not include sticky identifiers, hashes, or context fields."""
    result = request_local_details(
        claim_id="SA-000000001",
        requesting_investigator="test_user",
        justification="Test: release scope",
    )
    released = result["released_fields"]
    assert set(released.keys()) == set(QUASI_IDENTIFIER_FIELDS)

    forbidden = {
        "claimant_ssn", "device_fingerprint", "bank_routing", "bank_account",
        "claimant_ssn_hash", "device_fingerprint_hash",
        "bank_routing_hash", "bank_account_hash",
        "claim_id", "filing_state", "claim_date",
        "weekly_benefit_amount", "employer_ein",
    }
    for field in forbidden:
        assert field not in released


# ---------- Required justification ----------

def test_empty_justification_raises():
    with pytest.raises(ValueError, match="justification is required"):
        request_local_details(
            claim_id="SA-000000001",
            requesting_investigator="test_user",
            justification="",
        )


def test_whitespace_justification_raises():
    with pytest.raises(ValueError, match="justification is required"):
        request_local_details(
            claim_id="SA-000000001",
            requesting_investigator="test_user",
            justification="   ",
        )


# ---------- Routing ----------

def test_invalid_claim_id_prefix_raises():
    with pytest.raises(ValueError, match="prefix 'SA-' or 'SB-'"):
        request_local_details(
            claim_id="XX-000000001",
            requesting_investigator="test_user",
            justification="Test: invalid prefix",
        )


def test_nonexistent_claim_raises_and_audits():
    """A nonexistent claim must raise LookupError but still log a failed audit event."""
    with pytest.raises(LookupError):
        request_local_details(
            claim_id="SA-999999999",
            requesting_investigator="test_user_nonexistent",
            justification="Test: nonexistent claim",
        )

    # Verify the failure was audited
    recent = list_audit_events(limit=10)
    failed_events = [
        e for e in recent
        if e["event_type"] == "quasi_identifier_release_failed"
        and e["requesting_investigator"] == "test_user_nonexistent"
    ]
    assert len(failed_events) >= 1


# ---------- Audit logging ----------

def test_successful_release_writes_audit_event():
    result = request_local_details(
        claim_id="SA-000000001",
        requesting_investigator="audit_release_test",
        justification="Test: verifying audit log entry",
    )

    recent = list_audit_events(limit=10)
    matching = [
        e for e in recent
        if e["event_type"] == "quasi_identifier_release"
        and e["requesting_investigator"] == "audit_release_test"
        and e["details"]["claim_id"] == "SA-000000001"
    ]
    assert len(matching) >= 1
    assert matching[0]["event_hash"] == result["audit_event_hash"]
    assert matching[0]["details"]["justification"] == "Test: verifying audit log entry"