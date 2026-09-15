RF2 snapshot files at `/app/data/` contain tab-separated SNOMED CT data: concepts (`sct2_Concept_Snapshot_*.txt`), descriptions (`sct2_Description_Snapshot_*.txt`), relationships (`sct2_Relationship_Snapshot_*.txt`), and a simple reference set (`der2_Refset_SimpleSnapshot_*.txt`). A check-digit specification is at `/app/verhoeff_spec.txt`. An ECL ABNF grammar is at `/app/ecl_grammar.abnf`.

Create three executables:

**`/app/load-rf2`** — Produces `/app/snomed.db` (SQLite) from the RF2 files. Required tables:

- `concepts` — columns matching RF2 headers, plus `verhoeff_valid` (1 if the concept's SCTID passes the check defined in `/app/verhoeff_spec.txt`, 0 otherwise).
- `descriptions` — columns matching RF2 headers.
- `relationships` — columns matching RF2 headers.
- `refset_members` — columns matching RF2 headers.
- `transitive_closure` (`ancestor TEXT`, `descendant TEXT`) — complete IS-A (typeId `116680003`) closure over active, check-digit-valid concepts only.

The database must have at least 5 user-defined indices.

**`/app/ecl-eval`** — Evaluates an ECL expression (brief syntax per `/app/ecl_grammar.abnf`) against `/app/snomed.db`. First positional argument is the expression. Only active, check-digit-valid concepts appear in results.

Plain output (default): matching concept IDs sorted ascending, one per line. With `--json`: `{"total": N, "expansion": [{"conceptId": "SCTID", "display": "synonym"}, ...]}` sorted numerically by `conceptId`. Display values use the preferred synonym (description typeId `900000000000013009`).

All constraint operators defined in the grammar must work. Refinements filter by non-IS-A relationships using `=` and `!=`. Groups `{...}` constrain attributes to the same non-zero `relationshipGroup`. Dot notation extracts destination concepts. `^` = memberOf. `R` = reverse. Cardinality `[min..max]` (default `[1..*]`; `[0..0]` = negation). Keywords are case-insensitive. Arbitrary whitespace permitted. `|term|` annotations accepted and ignored. Exit 0 on success; non-zero with stderr message on invalid syntax.

**`/app/ecl-to-valueset`** — Accepts the same arguments as `ecl-eval`. Outputs FHIR R4 ValueSet JSON:

```json
{"resourceType":"ValueSet","status":"active","expansion":{"identifier":"urn:sha256:<hex>","timestamp":"2024-01-01T00:00:00Z","total":N,"contains":[{"system":"http://snomed.info/sct","code":"SCTID","display":"term"}]}}
```

`identifier` is `urn:sha256:` followed by the SHA-256 hex digest of the ECL expression string. `contains` sorted by `code` numerically.
