A SQLite database at `/app/idoft.db` contains five interlinked tables from the IDoFT (International Dataset of Flaky Tests) project: `pr_data` (Java Maven), `gr_data` (Java Gradle), `py_data` (Python), `odr_tests` (order-dependent test relationships), and `tic_fic_data` (test-introducing/flakiness-introducing commit records). Explore the schema and data with `sqlite3 /app/idoft.db`.

A partial reconciliation engine at `/app/reconciler/engine.py` implements three cross-dataset integrity checks, but the `check_odr_category_consistency` method contains a bug: it joins `pr_data` to `odr_tests` on `project_url` alone, failing to also match on the test name (`od_test`). This produces false positives when a project has some OD tests and some non-OD tests. Fix the JOIN so it matches on both `project_url` and `test_name = od_test`.

The engine is also missing four cross-referential integrity checks. Implement all of them using the following violation category names exactly:

- **`developer_fixed_no_fix_record`**: For each table (`pr_data`, `gr_data`), entries with `status = 'DeveloperFixed'` must have a corresponding record in `tic_fic_data` matched on both `project_url` and `test_name`. Flag entries that lack a match.
- **`odr_type_conflict`**: When a test appears in both `pr_data` and `odr_tests` (matched on `project_url` + `test_name`/`od_test`), its `od_test_type` must be consistent with its category. Specifically, `victim` conflicts with `OD-Brit` and `brittle` conflicts with `OD-Vic`. Flag these inconsistencies.
- **`orphaned_odr_reference`**: Entries in `odr_tests` whose `od_test` does not match any `test_name` in either `pr_data` or `gr_data` (by `project_url` + test name). Flag these orphaned references.
- **`orphaned_fix_record`**: Entries in `tic_fic_data` whose `test_name` does not match any entry in either `pr_data` or `gr_data` (by `project_url` + test name). Flag these orphaned records.

The three existing checks use these category names (keep them): `moved_to_gradle_unmatched`, `odr_category_mismatch`, `cross_build_duplicate`.

## Output format

Produce a JSON report at `/app/reconciliation_report.json` with the following structure:

```json
{
  "reconciliation_results": {
    "total_violations": <integer>,
    "by_category": {
      "<category_name>": <integer count>,
      ...
    },
    "violations": [
      {
        "category": "<category_name>",
        "source_table": "<table where the primary record lives>",
        "source_id": <integer row id in source table>,
        "details": "<human-readable description>"
      },
      ...
    ]
  }
}
```

The `total_violations` field must equal the length of the `violations` array. The sum of all values in `by_category` must equal `total_violations`. The schema at `/app/schema/report_schema.json` formally specifies these constraints; validate your output using `/app/validate.sh`.

Understanding the IDoFT flaky test taxonomy — OD/OD-Vic/OD-Brit victim-polluter-brittle-state-setter semantics, the distinction between order-dependent and non-order-dependent categories, and the status lifecycle — is essential for correctly implementing all checks.