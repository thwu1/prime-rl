An e-commerce analytics database at `/app/analytics.db` was bulk-imported from a legacy ERP system. `PRAGMA integrity_check` returns 'ok' and the schema is intact, but five standard report queries produce results that diverge from verified ERP ground truth. No list of specific issues is provided — you must discover them through forensic analysis.

Available resources:
- `/app/analytics.db` — the production database under investigation
- `/app/queries.sql` — the five report queries producing incorrect results
- `/app/audit_data.json` — a pre-migration audit snapshot from the ERP system containing: per-table row counts, aggregate column checksums, 30 sampled order_lines with verified correct values, per-category revenue totals, and per-product inventory balances
- `/app/schema_spec.md` — schema documentation including business rules and data type invariants that must hold
- `/app/discrepancy_notes.txt` — a data quality analyst's preliminary observations

Cross-reference the audit data against the current database state to identify all data integrity violations. The issues involve interactions between the import process and SQLite-specific storage and type behaviors not surfaced by `integrity_check`. Some corruptions mask or interact with others — a fix to one table may change the observable symptoms in queries that join across tables. You must determine the correct order of repairs.

Produce:

- `/app/analytics_repaired.db` — a repaired copy of the database where all five queries in `queries.sql` return results consistent with the ERP audit data. Do not modify the original `/app/analytics.db`.

- `/app/repair_report.json` — a structured repair analysis as a JSON object containing:
  - `phases`: an ordered array of repair phases. Each phase has: `phase_id` (integer), `depends_on` (array of phase_ids that must complete first), `issue` (short identifier), `description` (what is wrong), `evidence` (how you diagnosed it — which queries, functions, or cross-checks revealed the problem), `approach` (the repair you applied), `alternatives_considered` (at least one alternative approach and why you rejected it), `rows_affected` (integer count), and `sqlite_mechanism` (which SQLite behavior or design choice enabled this corruption to exist silently).
  - `preventive_measures`: an array of triggers or constraints added to the repaired database to prevent recurrence. Each entry has: `type` ("trigger"), `name` (trigger name), `target_table`, `definition` (the CREATE TRIGGER SQL), and `rationale` (why this prevents the specific issue).

- The repaired database must contain at least 3 `BEFORE INSERT` or `BEFORE UPDATE` triggers that enforce the business rules from `schema_spec.md`, preventing the discovered corruption patterns from recurring.