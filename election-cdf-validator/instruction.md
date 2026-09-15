Three NIST Common Data Format (CDF) JSON files in `/app/data/` represent a single election across the SP 1500-series:

- `bd.json` — Ballot Definition (SP 1500-20 v1): the authoritative entity registry (contests, contest selections, geographic units, parties, candidates, ballot styles)
- `cvr.json` — Cast Vote Records (SP 1500-103 v1): individual ballot records referencing BD entities by ID
- `err.json` — Election Results Reporting (SP 1500-100 v2): aggregate contest results referencing BD entities by ID

The dataset contains cross-format integrity failures: entity references in CVR and ERR that have no corresponding definition in BD, and at least one aggregate vote total in ERR that disagrees with the tally derivable from individual CVR records. Note that CVR data uses type-tagged JSON wrappers, snapshot indirection (`CurrentSnapshotId`), and indication flags that affect how votes should be counted.

Sample intra-format Schematron schemas are available in `/app/schemas/`.

Produce the following:

1. **`/app/merged.xml`** — A unified well-formed XML representation of all three CDF datasets with identifiable BD, CVR, and ERR sections.

2. **`/app/cross_cdf_rules.sch`** — An ISO Schematron schema that validates cross-format entity references (CVR->BD, ERR->BD). Must compile and detect the planted referential violations when applied to the merged XML.

3. **`/app/report.json`** — `{"violations": [...]}` where each entry has keys `violation_type`, `source_file`, `entity_id`, `description`. Must capture all cross-format referential integrity violations and all vote tally discrepancies between ERR aggregates and CVR-derived counts.