A C-CDA R2.1 clinical document at `/app/document.xml` contains multiple vocabulary and structural conformance violations distributed across its header demographics, participant metadata, and clinical sections. The document uses HL7 v3 and SDTC extension XML namespaces.

A rule-driven validation framework is defined by the configuration files under `/app/`:

- `validation_rules.xml` — Rule definitions mapping XPath expressions to named validators with associated reference data identifiers and severity levels
- `validator_types.json` — Behavioral specifications for each validator class referenced by the rules
- `valuesets/` — Reference data files (JSON format, one per OID) used during validation
- `scoring_config.json` — Parameters for computing the conformance score from violation counts

Study these files to understand how the validation framework operates, including the distinct semantics of each validator class, how each one interprets its configuration differently, and which attributes or content each one examines.

## Deliverables

1. **`/app/validator.py`** — A validation engine that parses the rule configuration, implements the correct validation logic for every validator class defined in the specifications, evaluates all rules against the clinical document, and identifies every conformance violation.

2. **`/app/report.json`** — JSON object containing:
   - `violations`: array where each entry includes `severity` (the conformance level from the rule), `found_value` (the non-conformant value detected in the document), and `validator_type` (the validator class name from the rule)
   - `summary`: object with `shall_count`, `should_count`, and `conformance_score` (computed per `/app/scoring_config.json`)

3. **`/app/fixed_document.xml`** — Corrected copy of the document where every detected violation has been repaired by substituting the invalid value with a valid alternative from the appropriate reference data. When multiple validators target the same XML node, each fix must compose correctly with others. The document's structural integrity, namespace declarations, and template identifiers must be preserved.