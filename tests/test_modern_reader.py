"""Tests for the modern source (MongoDB) reader."""

import json
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv()

from src.agent.tools.modern_reader import (
    read_modern_source,
    search_modern_source_by_hash,
)
from src.agent.tools.identifier_transform import (
    transform_identifier,
    STICKY_HASHED_FIELDS,
)


EXPECTED_FEDERATED_FIELDS = {
    "claim_id", "filing_state", "claim_date",
    "weekly_benefit_amount", "employer_ein",
    "claimant_ssn_hash", "device_fingerprint_hash",
    "bank_routing_hash", "bank_account_hash",
}


def test_reads_state_b_records():
    records = read_modern_source(max_records=10)
    assert len(records) == 10


def test_reads_all_state_b_when_unlimited():
    records = read_modern_source()
    assert len(records) == 800


def test_output_shape_matches_legacy_reader():
    """Modern reader must produce the exact same field set as legacy reader."""
    records = read_modern_source(max_records=5)
    for r in records:
        assert set(r.keys()) == EXPECTED_FEDERATED_FIELDS


def test_no_quasi_identifiers_in_output():
    forbidden = {"first_name", "last_name", "dob", "address", "ip_address"}
    records = read_modern_source(max_records=10)
    for r in records:
        for field in forbidden:
            assert field not in r


def test_filter_by_claim_id():
    """Should be able to fetch a single specific claim by ID."""
    records = read_modern_source(claim_id="SB-000000001")
    assert len(records) == 1
    assert records[0]["claim_id"] == "SB-000000001"


def test_search_by_seeded_ssn_hash_finds_match():
    """A seeded SSN-reuse pair must be findable via hash search in State B."""
    with open("data/ground_truth.json") as f:
        ground_truth = json.load(f)

    pair = ground_truth["pattern_1_ssn_reuse"][0]
    b_claim_id = pair["claim_ids"][1]  # State B claim
    shared_ssn = pair["shared_ssn_hash_input"]
    search_hash = transform_identifier(shared_ssn)

    matches = search_modern_source_by_hash("claimant_ssn_hash", search_hash)
    matching_claim_ids = [m["claim_id"] for m in matches]
    assert b_claim_id in matching_claim_ids


def test_search_with_invalid_identifier_type_raises():
    with pytest.raises(ValueError, match="identifier_type"):
        search_modern_source_by_hash("invalid_field", "a" * 64)


def test_search_with_wrong_length_hash_raises():
    with pytest.raises(ValueError, match="64 hex chars"):
        search_modern_source_by_hash("claimant_ssn_hash", "tooshort")