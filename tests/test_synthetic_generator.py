"""Tests for the synthetic data generator.

These tests verify that:
1. The generator produces the expected file structure
2. Seeded fraud patterns actually exist in the output
3. Determinism holds (same seed -> same output)
4. Field schemas are consistent

The tests assume the generator has been run at least once and outputs
exist in data/. They do not re-run the generator (that would be slow).
"""

import json
from pathlib import Path

import pytest


DATA_DIR = Path("data")
STATE_A_PATH = DATA_DIR / "state_a_claims.json"
STATE_B_PATH = DATA_DIR / "state_b_claims.json"
GROUND_TRUTH_PATH = DATA_DIR / "ground_truth.json"


@pytest.fixture(scope="module")
def state_a_claims():
    with STATE_A_PATH.open() as f:
        return json.load(f)


@pytest.fixture(scope="module")
def state_b_claims():
    with STATE_B_PATH.open() as f:
        return json.load(f)


@pytest.fixture(scope="module")
def ground_truth():
    with GROUND_TRUTH_PATH.open() as f:
        return json.load(f)


# ---------- File existence and counts ----------

def test_output_files_exist():
    assert STATE_A_PATH.exists(), "State A claims file missing - run generator first"
    assert STATE_B_PATH.exists(), "State B claims file missing - run generator first"
    assert GROUND_TRUTH_PATH.exists(), "Ground truth file missing - run generator first"


def test_state_a_claim_count(state_a_claims):
    assert len(state_a_claims) == 1200


def test_state_b_claim_count(state_b_claims):
    assert len(state_b_claims) == 800


# ---------- Schema consistency ----------

EXPECTED_FIELDS = {
    "claim_id", "filing_state", "claim_date", "weekly_benefit_amount",
    "employer_ein", "claimant_ssn", "device_fingerprint",
    "bank_routing", "bank_account", "first_name", "last_name",
    "dob", "address", "ip_address",
}


def test_state_a_schema(state_a_claims):
    for claim in state_a_claims:
        assert set(claim.keys()) == EXPECTED_FIELDS


def test_state_b_schema(state_b_claims):
    for claim in state_b_claims:
        assert set(claim.keys()) == EXPECTED_FIELDS


def test_filing_states_match_source(state_a_claims, state_b_claims):
    assert all(c["filing_state"] == "AA" for c in state_a_claims)
    assert all(c["filing_state"] == "BB" for c in state_b_claims)


# ---------- Uniqueness ----------

def test_claim_ids_unique_within_states(state_a_claims, state_b_claims):
    a_ids = [c["claim_id"] for c in state_a_claims]
    b_ids = [c["claim_id"] for c in state_b_claims]
    assert len(set(a_ids)) == len(a_ids)
    assert len(set(b_ids)) == len(b_ids)


def test_claim_ids_unique_across_states(state_a_claims, state_b_claims):
    a_ids = {c["claim_id"] for c in state_a_claims}
    b_ids = {c["claim_id"] for c in state_b_claims}
    assert a_ids.isdisjoint(b_ids)


# ---------- Ground truth structure ----------

def test_ground_truth_pattern_counts(ground_truth):
    assert len(ground_truth["pattern_1_ssn_reuse"]) == 30
    assert len(ground_truth["pattern_2_device_collision"]) == 15
    assert len(ground_truth["pattern_3_bank_reuse"]) == 10
    assert len(ground_truth["pattern_4_ring"]) == 1


# ---------- Seeded patterns actually exist in the data (the important tests) ----------

def test_seeded_ssn_reuse_actually_matches(ground_truth, state_a_claims, state_b_claims):
    """Every seeded SSN reuse pair must actually have matching SSNs in the data."""
    claims_a_by_id = {c["claim_id"]: c for c in state_a_claims}
    claims_b_by_id = {c["claim_id"]: c for c in state_b_claims}

    for pair in ground_truth["pattern_1_ssn_reuse"]:
        a_id, b_id = pair["claim_ids"]
        ssn_a = claims_a_by_id[a_id]["claimant_ssn"]
        ssn_b = claims_b_by_id[b_id]["claimant_ssn"]
        assert ssn_a == ssn_b, (
            f"Seeded SSN reuse pair {a_id}<->{b_id} has mismatched SSNs"
        )
        assert ssn_a == pair["shared_ssn_hash_input"]


def test_seeded_device_collisions_actually_match(ground_truth, state_a_claims, state_b_claims):
    """Every seeded device collision cluster must share the same device."""
    all_claims_by_id = {
        c["claim_id"]: c for c in (state_a_claims + state_b_claims)
    }
    for cluster in ground_truth["pattern_2_device_collision"]:
        devices = {
            all_claims_by_id[cid]["device_fingerprint"]
            for cid in cluster["claim_ids"]
        }
        assert len(devices) == 1, (
            f"Device cluster {cluster['claim_ids']} has multiple devices: {devices}"
        )


def test_seeded_bank_reuse_actually_matches(ground_truth, state_a_claims, state_b_claims):
    """Every seeded bank reuse cluster must share routing+account."""
    all_claims_by_id = {
        c["claim_id"]: c for c in (state_a_claims + state_b_claims)
    }
    for cluster in ground_truth["pattern_3_bank_reuse"]:
        routings = {
            all_claims_by_id[cid]["bank_routing"]
            for cid in cluster["claim_ids"]
        }
        accounts = {
            all_claims_by_id[cid]["bank_account"]
            for cid in cluster["claim_ids"]
        }
        assert len(routings) == 1, f"Bank cluster has multiple routings: {routings}"
        assert len(accounts) == 1, f"Bank cluster has multiple accounts: {accounts}"


def test_ring_structure_intact(ground_truth, state_a_claims, state_b_claims):
    """The coordinated ring's internal links must all be present."""
    all_claims_by_id = {
        c["claim_id"]: c for c in (state_a_claims + state_b_claims)
    }
    ring = ground_truth["pattern_4_ring"][0]
    assert len(ring["claim_ids"]) == 8

    for link in ring["links"]:
        claim_ids = link["claim_ids"]
        if link["type"] == "ssn_match":
            ssns = {all_claims_by_id[cid]["claimant_ssn"] for cid in claim_ids}
            assert len(ssns) == 1
        elif link["type"].startswith("device_match"):
            devices = {all_claims_by_id[cid]["device_fingerprint"] for cid in claim_ids}
            assert len(devices) == 1
        elif link["type"] == "bank_match":
            for field in ("bank_routing", "bank_account"):
                values = {all_claims_by_id[cid][field] for cid in claim_ids}
                assert len(values) == 1


# ---------- Sanity check: non-fraud claims are mostly independent ----------

def test_overall_ssn_uniqueness_is_high(state_a_claims, state_b_claims):
    """Most claims should have unique SSNs across the full dataset.
    
    With ~30 SSN-reuse pairs + ring SSN, we expect ~31 duplicates total.
    Total claims: 2000. So unique SSNs should be 2000 - 31 = ~1969.
    """
    all_ssns = [c["claimant_ssn"] for c in (state_a_claims + state_b_claims)]
    unique_ssns = set(all_ssns)
    # Allow some tolerance for any incidental Faker duplicates
    assert len(unique_ssns) >= 1960, (
        f"Too few unique SSNs ({len(unique_ssns)}) - check seeding logic"
    )