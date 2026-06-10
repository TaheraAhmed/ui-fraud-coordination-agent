# Scope Statement

This document defines what the UI Fraud Coordination Agent prototype demonstrates, what it simulates, and what is treated as future work. It exists to support honest evaluation by reviewers, judges, and other practitioners.

The document is updated as components are built. Each section indicates what is currently complete versus planned.

## Demonstrated

### Privacy-preserving identifier protocol *(complete as of Day 2)*

- Four sensitive identifier fields (`claimant_ssn`, `device_fingerprint`, `bank_routing`, `bank_account`) are transformed via HMAC-SHA256 under a federation-wide salt before they appear in any federation-exchange record.
- The transformation is implemented in `src/agent/tools/identifier_transform.py`. The function `transform_claim_identifiers` returns a dict whose structure mechanically excludes quasi-identifier fields — the privacy boundary is enforced by output shape, not by developer discipline.
- Hash output is a 64-character hex digest. The original value cannot be recovered from the digest, and two states independently hashing the same input under the same salt produce identical digests (enabling cross-state matching).
- Privacy properties are verified by two property tests:
  - `tests/test_identifier_transform.py::test_raw_pii_never_appears_in_federated_record` — proves the transformation function does not leak any of the source PII into its output.
  - `tests/test_legacy_reader.py::test_raw_pii_from_source_never_appears_in_reader_output` — proves the end-to-end legacy reading pipeline (EBCDIC binary → decoded record → federation-safe output) does not leak source PII.

### Legacy-agnostic adapter pattern *(complete as of Day 2 for the legacy side)*

- A single agent tool, `read_legacy_source`, reads EBCDIC fixed-width binary records (codepage cp037) defined by a COBOL copybook layout and produces federation-safe output records in a standardized intermediate representation.
- The copybook layout (`src/data/copybook_layout.txt`) uses real COBOL syntax (`01`, `05`, `PIC X(n)`, `PIC 9(n)`) and is parsed by `src/data/copybook_parser.py` into byte offsets.
- The total record length is 216 bytes per claim, covering 14 fields across three privacy categories.
- A parallel adapter for the modernized state (MongoDB document store) is planned for Day 3 and will share the same federation-safe output shape, demonstrating that the adapter pattern is genuinely format-agnostic.

### Synthetic claim population with seeded fraud typology *(complete as of Day 2)*

- 2,000 synthetic claims (1,200 in simulated State AA, 800 in simulated State BB) generated deterministically from a fixed random seed.
- Four fraud pattern types deliberately seeded into the population, matching documented cross-state fraud typologies:
  - 30 SSN-reuse pairs (matching the DOL OIG 991,793-SSN finding pattern)
  - 15 device-collision clusters (3-5 claims each, mix of within-state and cross-state)
  - 10 bank routing+account reuse clusters (2-4 claims each)
  - 1 coordinated fraud ring (8 claims linked through 4 different identifier overlaps)
- All seeded patterns documented in `data/ground_truth.json` with the exact claim IDs and identifier values involved, enabling reproducible evaluation of detection accuracy.
- Approximately 5.6% of claims are fraudulent (113 of 2,000), reflecting realistic fraud rates documented in DOL OIG reports.

## Simulated

### Single-process federation *(Day 2)*

The prototype runs both simulated states inside a single Python process. A production federation would run separate adapter agents inside each state's security perimeter, communicating over authenticated channels (mTLS, signed gRPC requests, or equivalent). The architectural argument generalizes to multi-process deployment, but the inter-process security model is not implemented.

### Single shared federation salt *(Day 2)*

The federation salt is loaded from a single `.env` file shared by all components in the process. Real deployment would require:
- A secure key management service (Google Cloud KMS, AWS KMS, or HashiCorp Vault) holding the federation salt.
- Per-federation salt distribution to each state's adapter agent.
- Periodic key rotation with versioned salt identifiers so historical hashes remain matchable.

None of this is implemented in the prototype. Key management is treated only as future work and addressed in the methodology paper.

### Federation coordination layer *(complete as of Day 3)*

- Both states' data sources expose the identical federation-safe record shape, mechanically proving the adapter pattern is format-agnostic (`src/agent/tools/legacy_reader.py` and `src/agent/tools/modern_reader.py`).
- The federation query tool searches both states by hashed identifier and returns matches without exposing raw values (`src/agent/tools/federation_query.py`). Every query writes a structured audit event.
- The audit log uses per-event SHA-256 hashes for tamper-evidence (`src/agent/tools/audit.py`). Hash chaining is future work.
- Quasi-identifier release requires explicit justification and produces an audit log entry per call (`src/agent/tools/local_lookup.py`). Failed lookups are also audited.

### Agent reasoning layer *(complete as of Day 3)*

- A single Gemini 2.5 Flash agent orchestrates four tools via Vertex AI function calling (`src/agent/orchestrator.py`).
- The agent classifies match results into three categories: self-matches (never reported), cross-state matches (primary mission, justifies quasi-identifier release), and within-state collisions (secondary findings).
- The system prompt is version-controlled (`src/agent/prompts/system_prompt.md`) and treated as code.
- End-to-end behavior validated on four scenarios: cross-state SSN reuse pair, no-match clean claim, coordinated ring with cross-state SSN link, coordinated ring with within-state device collision.

### Agent observability *(complete as of Day 3)*

- All Gemini reasoning steps and tool calls are captured as structured OpenTelemetry traces in Arize AX (`src/observability/arize_setup.py`).
- Auto-instrumentation via OpenInference's google-genai adapter — no manual span management required.
- Traces include input prompts, tool selections, tool arguments, tool results, and final responses. This supports the OMB M-25-21 transparency requirement.


### Investigator surface *(complete as of Day 4)*

- A Streamlit web interface (`src/ui/app.py`) lets investigators submit natural-language queries, view structured findings with due-process explanations, and review the audit trail.
- The interface is intentionally minimal: two tabs (Investigation, Audit Log), three example queries that exercise the agent's primary scenarios, and a session-aware audit log viewer.
- Investigation history is preserved per session, with each run showing the claim under investigation, completion status, duration, and the agent's structured response rendered as markdown.
- The audit log viewer renders structured MongoDB events with filtering (this session only versus all events) and expandable JSON details per event.
- The UI runs locally during development; Cloud Run deployment is planned for Day 6.

### Evaluation suite *(complete as of Day 5)*

- A labeled benchmark of 19 cases (`evals/test_cases.json`) spans five fraud typology categories: cross-state SSN reuse (n=8), cross-state bank reuse (n=4), within-state device collision (n=4), three ring-linkage variants (n=3), and clean claims with no expected matches (n=4). Cases are derived from the seeded fraud ground truth.
- The detection eval (`src/evals/run_eval.py`) invokes the agent on each test case, parses the structured findings, and compares against expected primary outcome and expected match sets. Scoring is precise: a case passes only if the primary outcome is correct AND every match array exactly matches the expected set.
- The LLM-as-judge narrative quality eval (`src/evals/narrative_judge.py`) scores each agent narrative along three dimensions — faithfulness, coverage, clarity — on a 1-5 integer scale with explicit rubric anchors. The judge is gemini-2.5-flash with low temperature and structured output.
- - Results across the full 19-case benchmark: 100% primary outcome accuracy, 100% overall pass rate, and a mean of 5.0 / 5 across all three narrative quality dimensions (faithfulness, coverage, clarity), with no case scoring below 5 on any dimension. Same-family judging and small sample size are documented as evaluation limitations.
- Both retry handling (for Vertex AI 429 RESOURCE_EXHAUSTED responses) and connection pooling (for MongoDB Atlas SSL handshake load) were added in service of eval reliability and remain in place as production-relevant resilience patterns.

### Legacy data format

State A's data is generated as EBCDIC-encoded fixed-width records following a COBOL copybook layout. This is representative of formats that real state UI mainframes still emit (GAO-23-105478), but it is generated synthetic data, not a real mainframe export. The copybook parser implements only the subset of COBOL syntax used in our layout (`PIC X(n)`, `PIC 9(n)`, level-numbered fields); full COBOL support including `REDEFINES`, `OCCURS`, `COMP-3` packed decimal, and signed fields is treated as future work.

### Investigator identity

The prototype uses a single mock investigator identity for any audit logging or queries. Production deployment would require federation with state workforce agency identity providers via SAML or OIDC.

### Synthetic claimant population

All claim data is synthetically generated using the `faker` library. No real claimant data is used, accessed, or referenced. The synthetic population is sized at 2,000 claims to enable end-to-end demonstration; production scale would be in the tens of millions per state, requiring different storage and indexing strategies.

## Evaluation Limitations

The evaluation results in this prototype are demonstrative, not conclusive. Several limitations apply:

- **Same-family LLM judging.** Both the agent under test and the LLM judge are gemini-2.5-flash. Same-family judging is known to introduce mild self-favorability bias in scoring. Mitigation strategies — cross-family judging or human-rated spot checks — are future work.

- **Controlled benchmark from seeded patterns.** Test cases are drawn from the synthetic fraud patterns deliberately seeded into the data. The agent's structural visibility into these pattern types is high. Performance on natural cross-state fraud — where patterns may not conform to the four seeded typologies — is not measured here.

- **Small sample size (n=19).** Results are not statistically conclusive. The benchmark is sized for demonstration and reproducibility within a hackathon timeline, not for statistical power. Larger and more diverse benchmarks are appropriate future work.

- **Deterministic data, deterministic seeded patterns.** The fraud pattern catalog (SSN reuse, device collision, bank reuse, single coordinated ring) is a small subset of the operationally observed fraud space documented in DOL OIG and GAO reports. Real-world fraud detection systems would need evaluation against a much broader pattern catalog.

We present results as evidence that the architecture is sound and that the agent's behavior aligns with the architectural intent. We do not claim production-grade detection performance.

### Network access controls *(introduced at Day 6 deployment)*

For the Cloud Run hosted deployment, MongoDB Atlas is configured to allow connections from any IP (`0.0.0.0/0`). This is acceptable for a hackathon prototype operating on synthetic claim data with no real PII. Production deployment of a system handling real UI claimant data would require one of:

- VPC peering between the Cloud Run service's project and MongoDB Atlas
- Atlas Private Endpoint via Google Cloud Private Service Connect
- A bastion / proxy architecture with allowlisted egress IPs

The application-layer privacy primitives (HMAC-SHA256 identifier transformation, structural exclusion of quasi-identifiers from federation exchange, audited per-claim release) remain in force regardless of network access controls.

## Future Work

- Multi-process deployment with mTLS-authenticated inter-state channels
- Real legacy system integration (COBOL copybook parsing against actual state-supplied mainframe exports)
- Production credential management via Google Cloud KMS for the federation salt, with versioned rotation
- Federated identity for investigator authentication
- Threshold-based release: cross-state matches surfaced only when k-anonymity thresholds are met
- Differential privacy mechanisms on aggregate statistics
- Fuzzy name matching using locality-sensitive hashing for the quasi-identifier corroboration step
- Full COBOL copybook support including `REDEFINES`, `OCCURS`, and packed decimal
- Integration with state workforce agency case management systems
- Formal security review and 20 CFR 603 legal review



