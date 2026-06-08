"""Tests for the federation query tool."""

import json

import pytest
from dotenv import load_dotenv

load_dotenv()

from src.agent.tools.federation_query import query_federation
from src.agent.tools.identifier_transform import transform_identifier


@pytest.fixture(scope="module")
def ground_truth():
    with open("data/ground_truth.json") as f:
        return json.load(f)


def test_seeded_ssn_reuse_pair_is_found(ground_truth):
    """A seeded cross-state SSN reuse pair must be findable via federation query."""
    pair = ground_truth["pattern_1_ssn_reuse"][0]
    a_id, b_id = pair["claim_ids"]
    target_hash = transform_identifier(pair["shared_ssn_hash_input"])

    result = query_federation(
        identifier_type="claimant_ssn_hash",
        hash_value=target_hash,
        requesting_investigator="test",
    )

    assert result["is_cross_state"] is True
    state_a_ids = {m["claim_id"] for m in result["matches_state_a"]}
    state_b_ids = {m["claim_id"] for m in result["matches_state_b"]}
    assert a_id in state_a_ids
    assert b_id in state_b_ids


def test_seeded_device_collision_is_found(ground_truth):
    """A seeded device collision cluster must be findable."""
    cluster = ground_truth["pattern_2_device_collision"][0]
    target_hash = transform_identifier(cluster["shared_device_hash_input"])

    result = query_federation(
        identifier_type="device_fingerprint_hash",
        hash_value=target_hash,
        requesting_investigator="test",
    )

    found_ids = (
        {m["claim_id"] for m in result["matches_state_a"]}
        | {m["claim_id"] for m in result["matches_state_b"]}
    )
    expected_ids = set(cluster["claim_ids"])
    assert expected_ids == found_ids


def test_nonexistent_hash_returns_zero_matches():
    """Querying a hash that doesn't match anything must return cleanly."""
    fake_hash = "0" * 64

    result = query_federation(
        identifier_type="claimant_ssn_hash",
        hash_value=fake_hash,
        requesting_investigator="test",
    )

    assert result["total_matches"] == 0
    assert result["is_cross_state"] is False
    assert result["matches_state_a"] == []
    assert result["matches_state_b"] == []


def test_invalid_identifier_type_raises():
    with pytest.raises(ValueError, match="identifier_type"):
        query_federation(
            identifier_type="not_a_real_field",
            hash_value="a" * 64,
            requesting_investigator="test",
        )


def test_invalid_hash_length_raises():
    with pytest.raises(ValueError, match="64-character"):
        query_federation(
            identifier_type="claimant_ssn_hash",
            hash_value="tooshort",
            requesting_investigator="test",
        )


def test_query_writes_audit_event():
    """Every federation query must result in an audit log entry."""
    from src.agent.tools.audit import list_audit_events

    fake_hash = "1" * 64
    result = query_federation(
        identifier_type="claimant_ssn_hash",
        hash_value=fake_hash,
        requesting_investigator="audit_verification_test",
    )

    recent = list_audit_events(limit=5)
    matching = [
        e for e in recent
        if e["event_type"] == "federation_query"
        and e["requesting_investigator"] == "audit_verification_test"
        and e["details"]["hash_value"] == fake_hash
    ]
    assert len(matching) >= 1
    assert matching[0]["event_hash"] == result["audit_event_hash"]


def test_returned_records_contain_no_quasi_identifiers(ground_truth):
    """Federation query results must never expose quasi-identifiers."""
    pair = ground_truth["pattern_1_ssn_reuse"][0]
    target_hash = transform_identifier(pair["shared_ssn_hash_input"])

    result = query_federation(
        identifier_type="claimant_ssn_hash",
        hash_value=target_hash,
        requesting_investigator="test",
    )

    forbidden = {"first_name", "last_name", "dob", "address", "ip_address"}
    for match in result["matches_state_a"] + result["matches_state_b"]:
        for field in forbidden:
            assert field not in match