"""Tool schema definitions for the Gemini agent.

These are the descriptions Gemini sees when deciding which tools to call.
They are the agent's interface to the system — Gemini reasons about the
descriptions, not about the underlying Python implementations.

The descriptions are deliberately specific about:
  - When to use each tool (and when not to)
  - What each parameter means
  - What the return value contains
  - Privacy boundaries (which tools require justifications, which release
    quasi-identifiers, etc.)

These descriptions are version-controlled. Treat changes here with the same
care as code changes — they materially affect agent behavior.
"""

from google.genai import types


READ_LEGACY_SOURCE_SCHEMA = types.FunctionDeclaration(
    name="read_legacy_source",
    description=(
        "Read federation-safe claim records from State AA's legacy mainframe data "
        "store (EBCDIC fixed-width binary format). Returns claim records with "
        "sensitive identifiers (SSN, device fingerprint, bank routing, bank "
        "account) replaced by HMAC-SHA256 hashes. Quasi-identifying fields "
        "(name, DOB, address, IP) are NOT included in the output — use "
        "request_local_details to retrieve those for a specific claim. "
        "Two modes: (1) Pass a specific claim_id (starts with 'SA-') to retrieve "
        "that one claim's federation-safe record. (2) Pass max_records without "
        "claim_id to read a sample of claims for exploration. Always prefer "
        "fetching a specific claim_id when you know which claim you're "
        "investigating — much more efficient than reading the full source."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "claim_id": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Optional. The specific State AA claim ID to retrieve "
                    "(must start with 'SA-'). When provided, returns just that "
                    "one claim's federation-safe record, or an empty list if "
                    "the claim is not in State AA."
                ),
            ),
            "max_records": types.Schema(
                type=types.Type.INTEGER,
                description=(
                    "Maximum number of records to return when claim_id is not "
                    "provided. Use small values (5-20) when exploring. Ignored "
                    "when claim_id is given."
                ),
            ),
        },
        required=[],
    ),
)


READ_MODERN_SOURCE_SCHEMA = types.FunctionDeclaration(
    name="read_modern_source",
    description=(
        "Read federation-safe claim records from State BB's modernized data "
        "store (MongoDB). Returns claim records with sensitive identifiers "
        "replaced by HMAC-SHA256 hashes. Quasi-identifying fields are NOT "
        "included — use request_local_details to retrieve those for a "
        "specific claim. "
        "Two modes: (1) Pass a specific claim_id (starts with 'SB-') to "
        "retrieve that one claim's federation-safe record. (2) Pass "
        "max_records without claim_id to sample claims. Always prefer "
        "fetching a specific claim_id when you know which claim you're "
        "investigating."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "claim_id": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Optional. The specific State BB claim ID to retrieve "
                    "(must start with 'SB-'). When provided, returns just that "
                    "one claim's federation-safe record, or an empty list if "
                    "the claim is not in State BB."
                ),
            ),
            "max_records": types.Schema(
                type=types.Type.INTEGER,
                description=(
                    "Maximum number of records to return when claim_id is not "
                    "provided. Ignored when claim_id is given."
                ),
            ),
        },
        required=[],
    ),
)
   


SEARCH_MODERN_SOURCE_BY_HASH_SCHEMA = types.FunctionDeclaration(
    name="search_modern_source_by_hash",
    description=(
        "Search State BB's modernized data store for claims whose hashed identifier "
        "matches a given hash value. Use this when you have a hash (from another claim "
        "or from a federation query) and want to find State BB claims sharing that "
        "identifier. Returns federation-safe records only — no quasi-identifiers."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "identifier_type": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Which hashed identifier field to search on. Must be one of: "
                    "'claimant_ssn_hash', 'device_fingerprint_hash', "
                    "'bank_routing_hash', 'bank_account_hash'."
                ),
            ),
            "hash_value": types.Schema(
                type=types.Type.STRING,
                description="The 64-character hex hash value to search for.",
            ),
        },
        required=["identifier_type", "hash_value"],
    ),
)


QUERY_FEDERATION_SCHEMA = types.FunctionDeclaration(
    name="query_federation",
    description=(
        "Search BOTH State AA and State BB for claims matching a hashed identifier. "
        "This is the primary cross-state coordination tool. It returns matches from "
        "both states and indicates whether the match is cross-state (claims in both). "
        "Every call writes an audit log entry. Use this whenever you have a hash "
        "and want to know if it appears in either state. Prefer this over calling "
        "the per-state tools individually."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "identifier_type": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Which hashed identifier field to search on. Must be one of: "
                    "'claimant_ssn_hash', 'device_fingerprint_hash', "
                    "'bank_routing_hash', 'bank_account_hash'."
                ),
            ),
            "hash_value": types.Schema(
                type=types.Type.STRING,
                description="The 64-character hex hash value to search for.",
            ),
            "requesting_investigator": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Identity of the investigator initiating this query. Used for "
                    "audit logging. Pass through whatever investigator identity you "
                    "received from the user."
                ),
            ),
        },
        required=["identifier_type", "hash_value", "requesting_investigator"],
    ),
)


REQUEST_LOCAL_DETAILS_SCHEMA = types.FunctionDeclaration(
    name="request_local_details",
    description=(
        "Request release of quasi-identifying fields (name, DOB, address, IP "
        "address) for a SPECIFIC claim. This is the ONLY way to obtain "
        "quasi-identifiers — they are never included in federation-safe records "
        "or query results. Every call is logged with the requesting investigator "
        "and stated justification. "
        "Use this only after a federation query has surfaced a claim that warrants "
        "investigation — typically when constructing a due-process explanation "
        "for a flagged cross-state match. Do not call speculatively or in bulk; "
        "every call is auditable and must have a clear justification."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "claim_id": types.Schema(
                type=types.Type.STRING,
                description=(
                    "The claim ID to look up. Must start with 'SA-' (State AA) "
                    "or 'SB-' (State BB)."
                ),
            ),
            "requesting_investigator": types.Schema(
                type=types.Type.STRING,
                description="Identity of the investigator requesting the release.",
            ),
            "justification": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Why this lookup is needed. Required and must be non-empty. "
                    "Example: 'Cross-state SSN hash match identified; retrieving "
                    "claimant name to construct due-process explanation.'"
                ),
            ),
        },
        required=["claim_id", "requesting_investigator", "justification"],
    ),
)



ALL_TOOL_SCHEMAS = [
    READ_LEGACY_SOURCE_SCHEMA,
    READ_MODERN_SOURCE_SCHEMA,
    SEARCH_MODERN_SOURCE_BY_HASH_SCHEMA,
    QUERY_FEDERATION_SCHEMA,
    REQUEST_LOCAL_DETAILS_SCHEMA,
]