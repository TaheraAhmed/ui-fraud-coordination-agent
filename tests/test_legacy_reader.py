"""Tests for the legacy EBCDIC source reader.

Key tests:
- Round-trip fidelity: claims read from EBCDIC match the JSON source
- Privacy: raw PII from the source file never appears in reader output
- Format handling: malformed files fail loudly, not silently
"""

import json
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv()

from src.agent.tools.legacy_reader import read_legacy_source
from src.agent.tools.identifier_transform import (
    transform_identifier,
    STICKY_HASHED_FIELDS,
)


DATA_DIR = Path("data")
SAMPLES_DIR = DATA_DIR / "samples"
STATE_A_JSON_PATH = DATA_DIR / "state_a_claims.json"
STATE_A_LEGACY_PATH = DATA_DIR / "state_a_legacy.dat"
STATE_A_LEGACY_SAMPLE_PATH = SAMPLES_DIR / "state_a_legacy_sample.dat"


@pytest.fixture(scope="module")
def source_claims():
    """The original JSON claims, for comparison against reader output."""
    with STATE_A_JSON_PATH.open() as f:
        return json.load(f)


# ---------- Basic functionality ----------

def test_reads_expected_number_of_records():
    records = read_legacy_source(STATE_A_LEGACY_PATH)
    assert len(records) == 1200


def test_max_records_caps_output():
    records = read_legacy_source(STATE_A_LEGACY_PATH, max_records=10)
    assert len(records) == 10


def test_reads_sample_file():
    records = read_legacy_source(STATE_A_LEGACY_SAMPLE_PATH)
    assert len(records) == 20


# ---------- Output shape ----------

EXPECTED_FEDERATED_FIELDS = {
    # Cross-state context
    "claim_id", "filing_state", "claim_date",
    "weekly_benefit_amount", "employer_ein",
    # Hashed sticky identifiers
    "claimant_ssn_hash", "device_fingerprint_hash",
    "bank_routing_hash", "bank_account_hash",
}


def test_output_has_only_federated_fields():
    """The reader output must contain exactly the federated-shape fields."""
    records = read_legacy_source(STATE_A_LEGACY_PATH, max_records=5)
    for r in records:
        assert set(r.keys()) == EXPECTED_FEDERATED_FIELDS


def test_no_quasi_identifiers_in_output():
    """Quasi-identifiers must not appear in any reader output."""
    forbidden = {"first_name", "last_name", "dob", "address", "ip_address"}
    records = read_legacy_source(STATE_A_LEGACY_PATH, max_records=20)
    for r in records:
        for forbidden_field in forbidden:
            assert forbidden_field not in r


def test_hashed_fields_are_64_hex_chars():
    """All hashed fields must be 64-character hex digests."""
    records = read_legacy_source(STATE_A_LEGACY_PATH, max_records=5)
    for r in records:
        for field in STICKY_HASHED_FIELDS:
            hash_value = r[f"{field}_hash"]
            assert len(hash_value) == 64
            assert all(c in "0123456789abcdef" for c in hash_value)


# ---------- Round-trip fidelity ----------

def test_first_record_matches_source(source_claims):
    """Cross-state context fields from EBCDIC must match the JSON source."""
    records = read_legacy_source(STATE_A_LEGACY_PATH, max_records=1)
    record = records[0]
    source = source_claims[0]

    assert record["claim_id"] == source["claim_id"]
    assert record["filing_state"] == source["filing_state"]
    assert record["claim_date"] == source["claim_date"]
    assert record["weekly_benefit_amount"] == source["weekly_benefit_amount"]
    assert record["employer_ein"] == source["employer_ein"]


def test_hash_matches_independent_transform(source_claims):
    """A hash from the reader must match an independent hash of the source value.
    
    This is the cross-state matching property: hashes are deterministic, so a
    State B claim independently hashing the same SSN produces the same digest.
    """
    records = read_legacy_source(STATE_A_LEGACY_PATH, max_records=1)
    reader_record = records[0]
    source_claim = source_claims[0]

    for field in STICKY_HASHED_FIELDS:
        independent_hash = transform_identifier(source_claim[field])
        reader_hash = reader_record[f"{field}_hash"]
        assert reader_hash == independent_hash, (
            f"Hash mismatch for {field}: reader output differs from "
            f"independent transformation"
        )


# ---------- The critical security test ----------

def test_raw_pii_from_source_never_appears_in_reader_output(source_claims):
    """Comprehensive: no raw PII from any of the first 50 source claims may
    appear anywhere in the reader's output for those claims.
    
    This is the second-most-important test in the codebase (after
    test_raw_pii_never_appears_in_federated_record). It proves the legacy
    reader, end-to-end from EBCDIC binary input, does not leak raw PII.
    """
    records = read_legacy_source(STATE_A_LEGACY_PATH, max_records=50)
    
    # Build the full string corpus of all reader output for these 50 records
    all_output_str = json.dumps(records)
    
    # Check every raw PII value from the source claims
    raw_pii_fields = list(STICKY_HASHED_FIELDS) + [
        "first_name", "last_name", "dob", "address", "ip_address",
    ]
    
    violations = []
    for source_claim in source_claims[:50]:
        for field in raw_pii_fields:
            raw_value = source_claim[field]
            if not raw_value or len(str(raw_value).strip()) < 4:
                # Skip very short values that might appear by chance
                continue
            if str(raw_value) in all_output_str:
                violations.append((source_claim["claim_id"], field, raw_value))
    
    assert not violations, (
        f"PRIVACY VIOLATION: Raw PII appeared in reader output:\n"
        + "\n".join(f"  {cid}.{fld} = {val!r}" for cid, fld, val in violations[:10])
    )


# ---------- Failure modes ----------

def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        read_legacy_source("data/nonexistent_file.dat")


def test_corrupted_file_raises(tmp_path):
    """A file whose size isn't a multiple of record length must error."""
    bad_file = tmp_path / "bad.dat"
    bad_file.write_bytes(b"\x00" * 100)  # Not a multiple of 216
    
    with pytest.raises(ValueError, match="not a multiple of record length"):
        read_legacy_source(bad_file)


# ---------- The seeded fraud is preserved through the reader ----------

def test_seeded_ssn_reuse_hash_matches_across_states(source_claims):
    """A seeded SSN-reuse pair must produce the same SSN hash from both sides.
    
    This is the end-to-end test of cross-state matching: if State A reads its
    legacy file and State B independently hashes the same SSN, both produce
    the same digest.
    """
    with open("data/ground_truth.json") as f:
        ground_truth = json.load(f)
    
    # Pick the first seeded SSN-reuse pair
    pair = ground_truth["pattern_1_ssn_reuse"][0]
    a_claim_id = pair["claim_ids"][0]
    shared_ssn = pair["shared_ssn_hash_input"]
    
    # Find this claim in the State A records and verify its hash
    records = read_legacy_source(STATE_A_LEGACY_PATH)
    a_record = next(r for r in records if r["claim_id"] == a_claim_id)
    
    # State B would independently hash the same SSN
    independent_b_hash = transform_identifier(shared_ssn)
    
    assert a_record["claimant_ssn_hash"] == independent_b_hash, (
        "Seeded SSN-reuse pair fails cross-state hash matching. "
        "Either the legacy reader's hashing or the ground truth is wrong."
    )