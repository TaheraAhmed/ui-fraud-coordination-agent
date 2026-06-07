"""Synthetic UI claim generator.

Generates a deterministic synthetic population of unemployment insurance claims
across two simulated states (AA and BB), with seeded fraud patterns matching
real-world cross-state fraud typologies documented by the DOL OIG and GAO.

Run as:
    uv run python -m src.data.synthetic_generator

Outputs:
    data/state_a_claims.json     - All State A claims (1200)
    data/state_b_claims.json     - All State B claims (800)
    data/ground_truth.json       - Seeded fraud pattern definitions

The generator is deterministic given a fixed RANDOM_SEED. The seeded patterns
match the fraud typology described in SCOPE.md.
"""

import json
import random
import secrets
import string
from collections import defaultdict
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from faker import Faker

from src.data.schema import Claim


# Determinism: fixed seed means rerunning produces identical output
RANDOM_SEED = 97

# Population sizing
STATE_A_COUNT = 1200
STATE_B_COUNT = 800
TOTAL_COUNT = STATE_A_COUNT + STATE_B_COUNT

# Output paths
DATA_DIR = Path("data")
GROUND_TRUTH_PATH = DATA_DIR / "ground_truth.json"
STATE_A_JSON_PATH = DATA_DIR / "state_a_claims.json"
STATE_B_JSON_PATH = DATA_DIR / "state_b_claims.json"

# ---------- Field generators ----------

def generate_ssn(faker: Faker) -> str:
    """Generate a synthetic SSN in XXX-XX-XXXX format."""
    return faker.ssn()


def generate_device_fingerprint() -> str:
    """Generate a 32-character hex device fingerprint."""
    return secrets.token_hex(16)


def generate_bank_routing(faker: Faker) -> str:
    """Generate a 9-digit bank routing number."""
    return faker.aba()


def generate_bank_account() -> str:
    """Generate a 12-digit bank account number."""
    return "".join(random.choices(string.digits, k=12))


def generate_employer_ein() -> str:
    """Generate a 9-digit employer EIN in XX-XXXXXXX format (no dash, 9 chars)."""
    return "".join(random.choices(string.digits, k=9))


def generate_ip(faker: Faker) -> str:
    """Generate a synthetic IPv4 address (padded to 15 chars in EBCDIC layout)."""
    return faker.ipv4()


def generate_claim_date(faker: Faker) -> str:
    """Generate a claim date within the past 2 years."""
    today = date.today()
    earliest = today - timedelta(days=730)
    d = faker.date_between(start_date=earliest, end_date=today)
    return d.isoformat()


def generate_dob(faker: Faker) -> str:
    """Generate a date of birth for an adult (age 22-65)."""
    d = faker.date_of_birth(minimum_age=22, maximum_age=65)
    return d.isoformat()


def generate_weekly_benefit() -> int:
    """Generate a realistic weekly benefit amount ($200-$700)."""
    return random.randint(200, 700)


# ---------- Claim builder ----------

def build_independent_claim(faker: Faker, state: str, claim_seq: int) -> Claim:
    """Build a single claim with all fields independently generated.

    These are the 'clean' claims with no intentional overlap. Fraud patterns
    are added later by mutating subsets of these claims.
    """
    return Claim(
        claim_id=f"S{state[1]}-{claim_seq:09d}",
        filing_state=state,
        claim_date=generate_claim_date(faker),
        weekly_benefit_amount=generate_weekly_benefit(),
        employer_ein=generate_employer_ein(),
        claimant_ssn=generate_ssn(faker),
        device_fingerprint=generate_device_fingerprint(),
        bank_routing=generate_bank_routing(faker),
        bank_account=generate_bank_account(),
        first_name=faker.first_name(),
        last_name=faker.last_name(),
        dob=generate_dob(faker),
        address=faker.street_address()[:50],  # Hard cap at 50 chars
        ip_address=generate_ip(faker),
    )


# ---------- Population generation ----------

def generate_base_population(faker: Faker) -> tuple[list[Claim], list[Claim]]:
    """Generate independent base populations for both states.

    Returns (state_a_claims, state_b_claims), all with unique identifiers.
    Fraud patterns are seeded after this step by mutating subsets.
    """
    claims_a = [
        build_independent_claim(faker, "AA", i + 1)
        for i in range(STATE_A_COUNT)
    ]
    claims_b = [
        build_independent_claim(faker, "BB", i + 1)
        for i in range(STATE_B_COUNT)
    ]
    return claims_a, claims_b

# ---------- Fraud pattern seeding ----------

def seed_fraud_patterns(
    claims_a: list[Claim],
    claims_b: list[Claim],
    faker: Faker,
) -> dict:
    """Seed four fraud pattern types and return the ground truth.

    Mutates claims in place. The base population starts with all independent
    identifiers; this function rewrites identifiers on selected claims to
    create the documented fraud patterns.

    Returns ground truth dict with structure:
        {
          "pattern_1_ssn_reuse": [
              {"claim_ids": [...], "shared_ssn": "...", "type": "ssn_reuse"},
              ...
          ],
          "pattern_2_device_collision": [...],
          "pattern_3_bank_reuse": [...],
          "pattern_4_ring": [...],
        }
    """
    ground_truth = {
        "pattern_1_ssn_reuse": [],
        "pattern_2_device_collision": [],
        "pattern_3_bank_reuse": [],
        "pattern_4_ring": [],
    }

    # Indices used so far; prevents the same claim being part of multiple patterns
    used_a = set()
    used_b = set()

    def pick_unused(claims: list[Claim], used: set, n: int) -> list[int]:
        """Pick n unused indices from claims list."""
        available = [i for i in range(len(claims)) if i not in used]
        chosen = random.sample(available, n)
        used.update(chosen)
        return chosen

    # ---- Pattern 1: SSN reuse across states (30 pairs) ----
    for _ in range(30):
        idx_a = pick_unused(claims_a, used_a, 1)[0]
        idx_b = pick_unused(claims_b, used_b, 1)[0]
        shared_ssn = generate_ssn(faker)
        claims_a[idx_a].claimant_ssn = shared_ssn
        claims_b[idx_b].claimant_ssn = shared_ssn
        ground_truth["pattern_1_ssn_reuse"].append({
            "claim_ids": [claims_a[idx_a].claim_id, claims_b[idx_b].claim_id],
            "shared_ssn_hash_input": shared_ssn,
            "type": "ssn_reuse",
        })

    # ---- Pattern 2: Device collisions (15 devices, 3-5 claims each) ----
    for _ in range(15):
        cluster_size = random.randint(3, 5)
        # Mix of within-state and cross-state distribution
        n_in_a = random.randint(1, cluster_size - 1)
        n_in_b = cluster_size - n_in_a
        idx_a_list = pick_unused(claims_a, used_a, n_in_a)
        idx_b_list = pick_unused(claims_b, used_b, n_in_b)
        shared_device = generate_device_fingerprint()
        cluster_claim_ids = []
        for idx in idx_a_list:
            claims_a[idx].device_fingerprint = shared_device
            cluster_claim_ids.append(claims_a[idx].claim_id)
        for idx in idx_b_list:
            claims_b[idx].device_fingerprint = shared_device
            cluster_claim_ids.append(claims_b[idx].claim_id)
        ground_truth["pattern_2_device_collision"].append({
            "claim_ids": cluster_claim_ids,
            "shared_device_hash_input": shared_device,
            "type": "device_collision",
        })

    # ---- Pattern 3: Bank routing+account reuse (10 combos, 2-4 claims each) ----
    for _ in range(10):
        cluster_size = random.randint(2, 4)
        n_in_a = random.randint(1, cluster_size - 1) if cluster_size > 1 else 1
        n_in_b = cluster_size - n_in_a
        idx_a_list = pick_unused(claims_a, used_a, n_in_a)
        idx_b_list = pick_unused(claims_b, used_b, n_in_b)
        shared_routing = generate_bank_routing(faker)
        shared_account = generate_bank_account()
        cluster_claim_ids = []
        for idx in idx_a_list:
            claims_a[idx].bank_routing = shared_routing
            claims_a[idx].bank_account = shared_account
            cluster_claim_ids.append(claims_a[idx].claim_id)
        for idx in idx_b_list:
            claims_b[idx].bank_routing = shared_routing
            claims_b[idx].bank_account = shared_account
            cluster_claim_ids.append(claims_b[idx].claim_id)
        ground_truth["pattern_3_bank_reuse"].append({
            "claim_ids": cluster_claim_ids,
            "shared_routing_hash_input": shared_routing,
            "shared_account_hash_input": shared_account,
            "type": "bank_reuse",
        })

    # ---- Pattern 4: Coordinated ring (8 claims sharing varied identifiers) ----
    # 4 in State A, 4 in State B. Within the ring:
    #   - 2 claims share an SSN (cross-state pair)
    #   - 2 claims share a device (within State A)
    #   - 2 claims share a device (within State B)
    #   - 2 claims share bank routing+account (cross-state pair)
    ring_a = pick_unused(claims_a, used_a, 4)
    ring_b = pick_unused(claims_b, used_b, 4)
    ring_claim_ids = [claims_a[i].claim_id for i in ring_a] + [claims_b[i].claim_id for i in ring_b]

    # Link 1: SSN match across A[0] and B[0]
    ring_ssn = generate_ssn(faker)
    claims_a[ring_a[0]].claimant_ssn = ring_ssn
    claims_b[ring_b[0]].claimant_ssn = ring_ssn

    # Link 2: Device collision within A: A[1] and A[2]
    ring_device_a = generate_device_fingerprint()
    claims_a[ring_a[1]].device_fingerprint = ring_device_a
    claims_a[ring_a[2]].device_fingerprint = ring_device_a

    # Link 3: Device collision within B: B[1] and B[2]
    ring_device_b = generate_device_fingerprint()
    claims_b[ring_b[1]].device_fingerprint = ring_device_b
    claims_b[ring_b[2]].device_fingerprint = ring_device_b

    # Link 4: Bank routing+account match across A[3] and B[3]
    ring_routing = generate_bank_routing(faker)
    ring_account = generate_bank_account()
    claims_a[ring_a[3]].bank_routing = ring_routing
    claims_a[ring_a[3]].bank_account = ring_account
    claims_b[ring_b[3]].bank_routing = ring_routing
    claims_b[ring_b[3]].bank_account = ring_account

    ground_truth["pattern_4_ring"].append({
        "claim_ids": ring_claim_ids,
        "links": [
            {"type": "ssn_match", "claim_ids": [claims_a[ring_a[0]].claim_id, claims_b[ring_b[0]].claim_id]},
            {"type": "device_match_state_a", "claim_ids": [claims_a[ring_a[1]].claim_id, claims_a[ring_a[2]].claim_id]},
            {"type": "device_match_state_b", "claim_ids": [claims_b[ring_b[1]].claim_id, claims_b[ring_b[2]].claim_id]},
            {"type": "bank_match", "claim_ids": [claims_a[ring_a[3]].claim_id, claims_b[ring_b[3]].claim_id]},
        ],
        "shared_ssn_hash_input": ring_ssn,
        "shared_device_a_hash_input": ring_device_a,
        "shared_device_b_hash_input": ring_device_b,
        "shared_routing_hash_input": ring_routing,
        "shared_account_hash_input": ring_account,
        "type": "ring",
    })

    return ground_truth


# ---------- Output writers ----------

def write_claims(claims: list[Claim], path: Path) -> None:
    """Write a list of claims to a JSON file."""
    with path.open("w") as f:
        json.dump([asdict(c) for c in claims], f, indent=2)


def write_ground_truth(ground_truth: dict, path: Path) -> None:
    """Write the ground truth dictionary to a JSON file."""
    with path.open("w") as f:
        json.dump(ground_truth, f, indent=2)



def main():
    """Generate the full synthetic dataset and write all output files."""
    random.seed(RANDOM_SEED)
    faker = Faker("en_US")
    faker.seed_instance(RANDOM_SEED)

    DATA_DIR.mkdir(exist_ok=True)

    # Generate base population of independent (non-fraudulent) claims
    claims_a, claims_b = generate_base_population(faker)

    # Seed fraud patterns into the population, tracking ground truth
    ground_truth = seed_fraud_patterns(claims_a, claims_b, faker)

    # Write outputs
    write_claims(claims_a, STATE_A_JSON_PATH)
    write_claims(claims_b, STATE_B_JSON_PATH)
    write_ground_truth(ground_truth, GROUND_TRUTH_PATH)

    print(f"Generated {len(claims_a)} claims for State AA -> {STATE_A_JSON_PATH}")
    print(f"Generated {len(claims_b)} claims for State BB -> {STATE_B_JSON_PATH}")
    print(f"Wrote ground truth ({sum(len(v) for v in ground_truth.values())} patterns) -> {GROUND_TRUTH_PATH}")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    main()