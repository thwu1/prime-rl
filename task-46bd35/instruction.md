The HMDA validation system at `/app/` has three conflicting sources of truth for rule behavior:

1. **Scala DSL rules** (`/app/scala_rules/`) — the authoritative reference using composable predicates (`when`, `is`, `oneOf`, `containedIn`, `implies`). When sources conflict, the Scala semantics are correct.
2. **Python pipeline** (`/app/pipeline/validator.py`) — the production engine containing implementation bugs.
3. **Regulatory specification** (`/app/regulatory_spec.md`) — human-authored rule descriptions with documentation errors that diverge from Scala.

Filing data is in an SQLite database at `/app/hmda_filings.db` with three tables: `institutions` (LEI, name, tax ID, agency code), `filings` (per-filing metadata and TS contact fields referencing institutions by LEI), and `lar_records` (pipe-delimited LAR records keyed by `filing_id` and `lar_index`). Field mappings between Scala paths and pipe-delimited indices are in `/app/scala_rules/field_mapping.md`. Rule thresholds are in `/app/pipeline/edits.conf` (HOCON format).

Reconcile all three sources, fix every bug in the Python pipeline, and implement any missing rules — including Q634, a filing-level macro quality rule described only in the regulatory spec with no Scala source. Extract all filing data from SQLite, run the corrected pipeline, and write one JSON report per filing to `/app/results/<filing_id>_report.json`.

Each report must have this structure:

```json
{
  "violations": [
    {"rule": "<rule_id>", "scope": "<ts|lar|filing>", "lar_index": "<int or null>", "message": "<description>"}
  ],
  "quality_flags": [
    {"rule": "<rule_id>", "lar_index": "<int or null>", "message": "<description>"}
  ],
  "summary": {
    "total_lars": "<int>",
    "violations_count": "<int>",
    "quality_flags_count": "<int>",
    "rules_triggered": ["<sorted unique rule IDs>"]
  }
}
```

- `scope`: `"ts"` for TS-level rules, `"lar"` for per-LAR rules, `"filing"` for cross-record rules.
- `lar_index`: 1-indexed LAR position; `null` for ts/filing scope.
- S and V rules produce violations. Q rules produce quality flags.