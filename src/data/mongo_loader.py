"""Load synthetic claim data into MongoDB Atlas.

This script populates the simulated State BB (modern data store) from the
generated synthetic claim JSON. It also creates the collections used by the
federation query tool and the audit log.

Run once after generating synthetic data:
    uv run python -m src.data.mongo_loader

Idempotent: re-running clears and reloads State BB. Audit log and federation
matches collections are preserved across runs (or cleared via --clear-all flag).

Collections created:
    state_b_claims      - State BB raw claim documents
    federation_matches  - Agent's working graph of cross-source matches
    audit_log           - Immutable log of every cross-state action

Indexes created on state_b_claims for the hash fields the federation query
will search on.
"""

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from pymongo import ASCENDING, MongoClient

from src.agent.tools.identifier_transform import transform_identifier


load_dotenv()

DATABASE_NAME = "ui_fraud_coordination"
STATE_B_COLLECTION = "state_b_claims"
FEDERATION_MATCHES_COLLECTION = "federation_matches"
AUDIT_LOG_COLLECTION = "audit_log"

STATE_B_JSON_PATH = Path("data/state_b_claims.json")


def get_db():
    """Return the MongoDB database handle, creating the client on demand."""
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        raise RuntimeError("MONGODB_URI not set in .env")
    client = MongoClient(uri)
    return client[DATABASE_NAME]


def load_state_b(clear_all: bool = False) -> None:
    """Load State B claims into MongoDB, optionally clearing other collections too."""
    db = get_db()

    # Clear existing State B data (always, for idempotency)
    state_b = db[STATE_B_COLLECTION]
    deleted = state_b.delete_many({}).deleted_count
    print(f"Cleared {deleted} existing State B claims")

    if clear_all:
        fed_deleted = db[FEDERATION_MATCHES_COLLECTION].delete_many({}).deleted_count
        audit_deleted = db[AUDIT_LOG_COLLECTION].delete_many({}).deleted_count
        print(f"Cleared {fed_deleted} federation match records")
        print(f"Cleared {audit_deleted} audit log entries")

    # Load and insert State B claims
    with STATE_B_JSON_PATH.open() as f:
        claims = json.load(f)

    # Precompute hashes for the sticky identifiers; store alongside the raw values.
    # In a real modernized state, hashes would be computed at query time. We
    # precompute here for query performance in the prototype.
    documents = []
    for claim in claims:
        doc = dict(claim)
        doc["claimant_ssn_hash"] = transform_identifier(claim["claimant_ssn"])
        doc["device_fingerprint_hash"] = transform_identifier(claim["device_fingerprint"])
        doc["bank_routing_hash"] = transform_identifier(claim["bank_routing"])
        doc["bank_account_hash"] = transform_identifier(claim["bank_account"])
        documents.append(doc)

    state_b.insert_many(documents)
    print(f"Inserted {len(documents)} claims into {STATE_B_COLLECTION}")

    # Create indexes on the hash fields for federation query performance
    for field in ("claimant_ssn_hash", "device_fingerprint_hash",
                  "bank_routing_hash", "bank_account_hash"):
        state_b.create_index([(field, ASCENDING)])
    state_b.create_index([("claim_id", ASCENDING)], unique=True)
    print("Created indexes on hash fields and claim_id")

    # Make sure the other two collections exist (creating an index is enough)
    db[FEDERATION_MATCHES_COLLECTION].create_index([("queried_at", ASCENDING)])
    db[AUDIT_LOG_COLLECTION].create_index([("timestamp", ASCENDING)])
    print(f"Initialized {FEDERATION_MATCHES_COLLECTION} and {AUDIT_LOG_COLLECTION}")


def main():
    parser = argparse.ArgumentParser(description="Load State B claims into MongoDB")
    parser.add_argument(
        "--clear-all",
        action="store_true",
        help="Also clear federation_matches and audit_log collections",
    )
    args = parser.parse_args()
    load_state_b(clear_all=args.clear_all)


if __name__ == "__main__":
    main()