Implement `/app/design_matrix.py` and `/app/pipeline.sh`.

**`/app/design_matrix.py`** must export:

```python
def dmatrix(formula: str, data: dict) -> tuple[list[str], list[list[float]]]:
```

`formula` is a statistical model formula string. `data` maps variable names to lists of values — strings indicate categorical variables, numbers indicate numerical variables. The function returns `(column_names, matrix_rows)`: a list of column name strings and a row-major matrix of floats.

The complete behavioral specification is defined by the golden reference outputs in `/app/reference/*.json` and the test cases in `/app/init.sql`. These are the authoritative specification; study them to determine every aspect of the required behavior.

**Provided files** (do not modify):

- `/app/cli.py` — CLI wrapper that reads CSV from stdin and calls `dmatrix`. Usage: `python3 /app/cli.py "formula" [--json]`
- `/app/validate.py` — validates `dmatrix` output against `/app/reference/*.json` golden outputs. Must exit 0 when all cases match.
- `/app/init.sql` — SQLite schema defining tables `test_suites`, `test_cases`, `expected_outputs`, and `pipeline_results`, populated with 25 test cases across 5 suites
- `/app/Makefile` — targets: `validate`, `pipeline`, `report`

**`/app/pipeline.sh`** must use `sqlite3`, `jq`, and `/app/cli.py` together to validate every test case from `/app/init.sql` against its expected output. Requirements:

- Initialize `/app/results.db` from `/app/init.sql`
- Populate the `pipeline_results` table (schema defined in `/app/init.sql`) with exactly one row per test case. Passing results must have non-NULL `columns_json` and `matrix_json`
- Use approximate numeric comparison (tolerance 1e-6) for matrix values
- Exit 0 only if all cases pass

**Success criteria:** all tests in `/tests/test_state.py` pass.
