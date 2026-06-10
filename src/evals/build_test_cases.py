"""Generate the labeled evaluation test case set from ground truth.

Reads data/ground_truth.json and emits evals/test_cases.json. Each test case
specifies a claim to investigate, the expected primary outcome, the expected
cross-state matches (if any), and the expected within-state secondary matches
(if any). This is the labeled benchmark the evaluation suite scores against.

Test case categories (target distribution for ~25 cases):
  - 8x cross_state_ssn: query a State A claim from a seeded SSN-reuse pair,
                        expect cross-state SSN match with the paired State B claim
  - 4x cross_state_bank: query a State A claim from a seeded bank-reuse cluster
                        that has at least one cross-state member, expect match
  - 4x within_state_device: query a State A claim from a device-collision
                        cluster where matches are only in State A, expect
                        within-state secondary finding only
  - 2x ring_ssn_link: query a ring claim that's part of the SSN-match link,
                        expect cross-state SSN match
  - 2x ring_bank_link: query a ring claim from the bank-match link, expect
                        cross-state bank match
  - 2x ring_within_state_device: query a ring claim from a within-state
                        device match, expect within-state secondary only
  - 4x clean: query a State A claim with no seeded patterns, expect no matches

Run with:
    uv run python -m src.evals.build_test_cases
"""

import json
import random
from pathlib import Path


GROUND_TRUTH_PATH = Path("data/ground_truth.json")
STATE_A_CLAIMS_PATH = Path("data/state_a_claims.json")
OUTPUT_PATH = Path("evals/test_cases.json")

RANDOM_SEED = 17  # Different from generator seed so the cases are independent

PRIMARY_OUTCOMES = {
    "cross_state": "At least one cross-state hash match exists",
    "within_state_only": "No cross-state match, but at least one within-state collision",
    "no_match": "No matches of any kind beyond self-match",
}


def load_ground_truth() -> dict:
    with GROUND_TRUTH_PATH.open() as f:
        return json.load(f)


def load_clean_state_a_ids(ground_truth: dict) -> list[str]:
    """Return State A claim IDs that are NOT in any seeded fraud pattern."""
    fraud_ids = set()
    for pattern_key in (
        "pattern_1_ssn_reuse",
        "pattern_2_device_collision",
        "pattern_3_bank_reuse",
        "pattern_4_ring",
    ):
        for pattern in ground_truth[pattern_key]:
            fraud_ids.update(pattern["claim_ids"])

    with STATE_A_CLAIMS_PATH.open() as f:
        claims = json.load(f)
    return [c["claim_id"] for c in claims if c["claim_id"] not in fraud_ids]


def build_cross_state_ssn_cases(ground_truth: dict, n: int) -> list[dict]:
    """Cases where querying a State A claim reveals a cross-state SSN match."""
    cases = []
    pairs = ground_truth["pattern_1_ssn_reuse"][:n]
    for pair in pairs:
        a_id, b_id = pair["claim_ids"]
        cases.append({
            "case_id": f"ssn_reuse_{a_id}",
            "category": "cross_state_ssn",
            "query_claim_id": a_id,
            "expected_primary": "cross_state",
            "expected_cross_state_matches": {
                "claimant_ssn_hash": [b_id],
            },
            "expected_within_state_matches": {},
            "notes": "Seeded SSN reuse pair; agent should find cross-state SSN match.",
        })
    return cases


def build_cross_state_bank_cases(ground_truth: dict, n: int) -> list[dict]:
    """Cases where querying a State A claim from a bank-reuse cluster reveals
    a cross-state bank match. Only use clusters that span both states."""
    cases = []
    candidates = []
    for cluster in ground_truth["pattern_3_bank_reuse"]:
        a_claims = [c for c in cluster["claim_ids"] if c.startswith("SA-")]
        b_claims = [c for c in cluster["claim_ids"] if c.startswith("SB-")]
        if a_claims and b_claims:
            candidates.append((cluster, a_claims, b_claims))
        if len(candidates) >= n:
            break

    for cluster, a_claims, b_claims in candidates[:n]:
        query_id = a_claims[0]
        # Expected matches: all other claims in the cluster
        cs_other_state = b_claims
        ws_same_state = [c for c in a_claims if c != query_id]
        cases.append({
            "case_id": f"bank_reuse_{query_id}",
            "category": "cross_state_bank",
            "query_claim_id": query_id,
            "expected_primary": "cross_state",
            "expected_cross_state_matches": {
                "bank_routing_hash": cs_other_state,
                "bank_account_hash": cs_other_state,
            },
            "expected_within_state_matches": (
                {"bank_routing_hash": ws_same_state, "bank_account_hash": ws_same_state}
                if ws_same_state else {}
            ),
            "notes": "Seeded bank reuse with cross-state membership; agent should find cross-state bank match.",
        })
    return cases


def build_within_state_device_cases(ground_truth: dict, n: int) -> list[dict]:
    """Cases where querying a State A claim from a device-collision cluster
    that has NO State B members yields a within-state-only finding."""
    cases = []
    candidates = []
    for cluster in ground_truth["pattern_2_device_collision"]:
        a_claims = [c for c in cluster["claim_ids"] if c.startswith("SA-")]
        b_claims = [c for c in cluster["claim_ids"] if c.startswith("SB-")]
        # We want clusters with State A members but NO State B members
        if a_claims and not b_claims and len(a_claims) >= 2:
            candidates.append((cluster, a_claims))
        if len(candidates) >= n:
            break

    for cluster, a_claims in candidates[:n]:
        query_id = a_claims[0]
        other_a = [c for c in a_claims if c != query_id]
        cases.append({
            "case_id": f"within_state_device_{query_id}",
            "category": "within_state_device",
            "query_claim_id": query_id,
            "expected_primary": "within_state_only",
            "expected_cross_state_matches": {},
            "expected_within_state_matches": {
                "device_fingerprint_hash": other_a,
            },
            "notes": "Seeded within-state-only device collision; agent should find within-state secondary, no cross-state.",
        })
    return cases


def build_ring_cases(ground_truth: dict) -> list[dict]:
    """Ring cases — each linkage in the ring becomes a separate test case."""
    ring = ground_truth["pattern_4_ring"][0]
    cases = []

    for link in ring["links"]:
        link_type = link["type"]
        link_claims = link["claim_ids"]

        if link_type == "ssn_match":
            # Cross-state SSN
            a_id = next(c for c in link_claims if c.startswith("SA-"))
            b_id = next(c for c in link_claims if c.startswith("SB-"))
            cases.append({
                "case_id": f"ring_ssn_{a_id}",
                "category": "ring_ssn_link",
                "query_claim_id": a_id,
                "expected_primary": "cross_state",
                "expected_cross_state_matches": {"claimant_ssn_hash": [b_id]},
                "expected_within_state_matches": {},
                "notes": "Ring claim with cross-state SSN linkage.",
            })

        elif link_type == "bank_match":
            a_id = next(c for c in link_claims if c.startswith("SA-"))
            b_id = next(c for c in link_claims if c.startswith("SB-"))
            cases.append({
                "case_id": f"ring_bank_{a_id}",
                "category": "ring_bank_link",
                "query_claim_id": a_id,
                "expected_primary": "cross_state",
                "expected_cross_state_matches": {
                    "bank_routing_hash": [b_id],
                    "bank_account_hash": [b_id],
                },
                "expected_within_state_matches": {},
                "notes": "Ring claim with cross-state bank linkage.",
            })

        elif link_type == "device_match_state_a":
            # Within-state State A
            query_id, other = link_claims[0], link_claims[1]
            cases.append({
                "case_id": f"ring_device_a_{query_id}",
                "category": "ring_within_state_device",
                "query_claim_id": query_id,
                "expected_primary": "within_state_only",
                "expected_cross_state_matches": {},
                "expected_within_state_matches": {
                    "device_fingerprint_hash": [other],
                },
                "notes": "Ring claim with within-state device linkage (State A).",
            })

        # device_match_state_b is skipped — we query State A claims only

    return cases


def build_clean_cases(ground_truth: dict, n: int) -> list[dict]:
    """Cases where querying a non-fraud State A claim should produce no matches."""
    rng = random.Random(RANDOM_SEED)
    clean_ids = load_clean_state_a_ids(ground_truth)
    chosen = rng.sample(clean_ids, n)
    cases = []
    for cid in chosen:
        cases.append({
            "case_id": f"clean_{cid}",
            "category": "clean",
            "query_claim_id": cid,
            "expected_primary": "no_match",
            "expected_cross_state_matches": {},
            "expected_within_state_matches": {},
            "notes": "Clean claim not in any seeded fraud pattern; expect no matches.",
        })
    return cases


def main():
    ground_truth = load_ground_truth()

    all_cases = []
    all_cases.extend(build_cross_state_ssn_cases(ground_truth, n=8))
    all_cases.extend(build_cross_state_bank_cases(ground_truth, n=4))
    all_cases.extend(build_within_state_device_cases(ground_truth, n=4))
    all_cases.extend(build_ring_cases(ground_truth))
    all_cases.extend(build_clean_cases(ground_truth, n=4))

    # Summarize by category
    by_category: dict[str, int] = {}
    for case in all_cases:
        by_category[case["category"]] = by_category.get(case["category"], 0) + 1

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w") as f:
        json.dump({
            "total": len(all_cases),
            "by_category": by_category,
            "cases": all_cases,
        }, f, indent=2)

    print(f"Wrote {len(all_cases)} test cases to {OUTPUT_PATH}")
    print("Distribution by category:")
    for cat, count in sorted(by_category.items()):
        print(f"  {cat:<30} {count:>3}")


if __name__ == "__main__":
    main()