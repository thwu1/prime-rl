A CMS electronic clinical quality measure (eCQM) is specified using Clinical Quality Language (CQL) at `/app/cql/CMS165v14.cql`. This CQL source is the complete and authoritative specification for all evaluation logic — population criteria, clinical data queries, temporal interval operations, and observation-level qualifications.

The formal FHIR Measure resource at `/app/measure/CMS165v14.json` defines the measure's population structure — mapping population identifiers to their corresponding CQL expression names and specifying the scoring methodology. Its deeply nested FHIR structure must be navigated to extract population-to-expression relationships.

Twenty FHIR R4 patient bundles are in `/app/patients/`. Each bundle is a JSON collection containing Patient, Condition, Encounter, Observation, and/or Procedure resources representing a patient's clinical record.

Clinical terminology for the measure is stored in a SQLite database at `/app/terminology.db`. The database schema:

- Table `value_sets`: columns `id` (INTEGER PK), `url` (TEXT), `oid` (TEXT), `title` (TEXT), `version` (TEXT)
- Table `codes`: columns `id` (INTEGER PK), `value_set_id` (INTEGER FK → value_sets.id), `system` (TEXT), `code` (TEXT), `display` (TEXT), `version` (TEXT)
- Indexes on `codes(value_set_id, system, code)`, `value_sets(title)`, `value_sets(url)`

The `valueset` declarations in the CQL source reference value sets by title (e.g., `"Essential Hypertension"`) which correspond to `value_sets.title` entries. Membership checks require joining `value_sets` and `codes` tables via SQL. The `sqlite3` CLI tool, Python `sqlite3` module, and `jq` are available in the environment.

The measurement period is specified in `/app/measurement_period.json`.

Build an evaluation pipeline that processes each patient bundle through the CQL measure logic and writes per-patient population membership results to `/app/results.json`:

```json
{
  "patient_001": {"IPP": true, "DENOM": true, "DENEX": false, "NUMER": true},
  "patient_002": {"IPP": false, "DENOM": false, "DENEX": false, "NUMER": false}
}
```

Each patient entry must contain boolean values for all four population keys (IPP, DENOM, DENEX, NUMER). The evaluation must faithfully implement all CQL definitions, fluent functions, and helper logic from the CQL source, including correct handling of the CQL type system and null semantics.