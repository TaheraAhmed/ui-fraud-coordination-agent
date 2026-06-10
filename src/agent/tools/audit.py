"""Audit log primitives for cross-state federation operations.

Every cross-state action — federation query, quasi-identifier release —
must write a structured event to the audit log collection. The audit log
is the operational realization of 20 CFR 603's confidentiality requirements:
even when information is shared, it is logged with full provenance.

This module provides the primitive used by other tools. It is not a tool
the agent calls directly — the agent's tools call this internally.
"""

import hashlib
import os
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from pymongo import MongoClient


load_dotenv()


DATABASE_NAME = "ui_fraud_coordination"
AUDIT_LOG_COLLECTION = "audit_log"


# Lazy-initialized, module-level client. Reused across all calls.
_mongo_client: MongoClient | None = None


def _get_audit_collection():
    """Return the audit log collection. Uses a shared, lazy-initialized client."""
    global _mongo_client
    if _mongo_client is None:
        uri = os.environ.get("MONGODB_URI")
        if not uri:
            raise RuntimeError("MONGODB_URI not set in .env")
        _mongo_client = MongoClient(uri)
    return _mongo_client[DATABASE_NAME][AUDIT_LOG_COLLECTION]


def _ensure_utc(dt: datetime) -> datetime:
    """Normalize a datetime to UTC-aware form.

    MongoDB BSON dates have no timezone; pymongo returns them as naive UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _compute_event_hash(event: dict) -> str:
    """Compute a SHA-256 hash of the event payload for tamper-evidence.

    In a real audit system, this would be chained: each event includes the
    hash of the previous event, creating a tamper-evident chain. The prototype
    computes per-event hashes only; chain integrity is future work.
    """
    canonical = repr(sorted(event.items()))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_audit_event(
    event_type: str,
    requesting_investigator: str,
    details: dict[str, Any],
) -> dict:
    """Write a structured audit event and return the persisted record.

    Args:
        event_type: Category of audit event, e.g. "federation_query" or
            "quasi_identifier_release".
        requesting_investigator: Identity of the investigator who initiated
            the action. In the prototype this is a free-form string; production
            would require federated identity attestation.
        details: Event-specific payload. Should be JSON-serializable.

    Returns:
        The persisted audit event including its computed integrity hash.
    """
    timestamp = datetime.now(timezone.utc)
    event = {
        "event_type": event_type,
        "requesting_investigator": requesting_investigator,
        "timestamp": timestamp,
        "details": details,
    }
    event["event_hash"] = _compute_event_hash(event)

    collection = _get_audit_collection()
    result = collection.insert_one(event)

    # Re-fetch to return the persisted form (with _id stripped for cleanliness)
    persisted = collection.find_one(
        {"_id": result.inserted_id},
        projection={"_id": 0},
    )
    return persisted


def list_audit_events(limit: int = 50) -> list[dict]:
    """Retrieve recent audit events, newest first. Used for inspection only."""
    collection = _get_audit_collection()
    cursor = collection.find({}, projection={"_id": 0}).sort("timestamp", -1).limit(limit)
    return list(cursor)