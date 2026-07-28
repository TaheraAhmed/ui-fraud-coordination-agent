# Citations

Federal sources informing the design and problem framing of this project.
Each entry notes what the source documents and where it appears in this work.

## Fraud quantification

- **U.S. DOL OIG, Report 19-22-005-03-315.** Documents pandemic-era UI
  fraud, including 991,793 Social Security Numbers filed across multiple
  states simultaneously and at least $28.9 billion in improper payments.
  Basis for the problem statement and the cross-state detection scenario.

- **U.S. DOL OIG, Report 19-25-009-03-315.** Multi-state filing analysis
  identifying a single SSN used to file across 11 states. Motivates the
  transformed-identifier matching protocol.

- **GAO-23-106696.** Estimates $100–135 billion in pandemic-era UI fraud.
  Establishes national scale of the problem.

## System modernization

- **GAO-23-105478.** Finds that the majority of state UI systems run on
  legacy mainframe infrastructure, much of it 40–50 years old, and that
  6 of 8 sampled states had not completed modernization. Basis for the
  EBCDIC/COBOL legacy adapter and the heterogeneity problem.

## Regulatory framework

- **20 CFR Part 603.** Governs disclosure and confidentiality of UI claim
  information. Defines the constraint the transformed-identifier protocol
  is designed to satisfy.

- **DOL Proposed Rulemaking, Federal Register 2025-16645.** Proposes
  requiring rather than merely permitting data disclosure for fraud
  detection. Context for the coordination approach.

## AI governance

- **OMB Memorandum M-25-21.** Federal AI governance requirements,
  including transparency and accountability in agency decision-making.
  Basis for the due-process explanation and audit design.

- **NIST AI Risk Management Framework (AI RMF 1.0).** Explainability,
  accountability, and governance as core characteristics of trustworthy
  AI. Informs the structured-findings-plus-narrative output.

- **NIST SP 800-63-4.** Digital identity guidelines, including synthetic
  identity threats. Context for identifier-based matching.
