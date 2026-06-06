# Scope Statement

This document defines what the UI Fraud Coordination Agent prototype demonstrates, what it simulates, and what is treated as future work. It exists to support honest evaluation by reviewers, judges, and other practitioners.

## Demonstrated

- **Adapter pattern for heterogeneous source formats.** A single Gemini agent reads both EBCDIC fixed-width records (representing a legacy mainframe state UI system) and MongoDB JSON documents (representing a modernized state) through format-specific tools that normalize to a shared intermediate representation.
- **Transformed-identifier protocol.** Sensitive identifiers (Social Security Numbers, device fingerprints, bank routing numbers) are cryptographically transformed using HMAC-SHA256 under a federation-wide salt before any cross-source query. Raw PII never crosses simulated state boundaries.
- **Cross-source pattern detection.** The agent identifies multi-state fraud patterns including shared-SSN reuse, device collisions, and small fraud rings, using only transformed identifiers.
- **Three-part due-process explanation surface.** Every flagged finding produces a connections list, contribution weights, and a plain-language narrative grounded in the underlying structured evidence.
- **Audit trail.** Every cross-source query writes an immutable record to a MongoDB audit collection with timestamp, transformed identifier queried, requesting investigator, and hash chain.
- **Agent reasoning observability.** Arize AX traces every agent reasoning step, tool call, and decision. A labeled evaluation set measures pattern detection accuracy.
- **Distributed tracing.** Dynatrace captures the end-to-end flow from investigator query through agent reasoning, tool execution, and audit log write.

## Simulated

- **Two states.** The prototype runs two simulated state UI data sources in a single process. A real federation would run separate adapter agents inside each state's security perimeter, communicating over authenticated channels. The architectural argument generalizes, but the multi-process security model is not implemented.
- **Legacy data format.** State A's data is generated as EBCDIC-encoded fixed-width records following a COBOL copybook-style schema. This is representative of formats real state UI mainframes still emit, but it is generated synthetic data, not a real mainframe export.
- **Federation salt distribution.** The prototype shares a salt across both adapter tools in the same process. Real deployment would require secure key management (e.g., Google Cloud KMS) for per-federation salt distribution. The methodology paper addresses this.
- **Investigator identity.** The prototype uses a single mock investigator identity for audit logging. Production would require federated identity (e.g., SAML/OIDC integration with state workforce agency identity providers).
- **Synthetic claimant population.** All claim data is synthetically generated. No real claimant data is used or accessed.

## Future Work

- Multi-process deployment with TLS-authenticated inter-state channels
- Real legacy system integration (COBOL copybook parsing against actual mainframe exports)
- Production credential management via Google Cloud KMS or AWS KMS
- Federated identity for investigator authentication
- Threshold-based release: cross-state matches surfaced only when k-anonymity thresholds are met
- Differential privacy mechanisms on aggregate statistics
- Integration with state workforce agency case management systems
- Formal security review and 20 CFR 603 legal review

