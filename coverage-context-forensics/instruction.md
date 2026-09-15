The Python project at `/app/` contains a multi-module calculation library (`/app/calclib/`) with a test suite (`/app/tests/`). The coverage configuration at `/app/.coveragerc` is broken — coverage measurement does not work correctly as-is.

Your goal is to get coverage.py working properly for this project. The final coverage setup must satisfy all of the following requirements:

- **Branch coverage** is enabled and arc data is collected.
- **Dynamic contexts** track which test function covers which lines (using `test_function` granularity).
- **Multiprocessing** workers spawned by the test suite are traced and their data is included.
- **All source modules** under `calclib/` are measured — none are incorrectly excluded.
- **Exclusion patterns** do not suppress measurement of real application code paths.

After fixing the configuration, run the full test suite under coverage, combine all parallel data into a single `.coverage` database at `/app/.coverage`, and produce `/app/impact_report.json` by querying the coverage data.

The report must have this structure:

```json
{
  "coverage_summary": {
    "<relative_path>": {
      "lines_covered": "<int>",
      "lines_total": "<int>",
      "branches_covered": "<int>",
      "branches_total": "<int>"
    }
  },
  "context_mapping": {
    "<context_name>": ["<file1>", "<file2>"]
  },
  "exclusive_coverage": {
    "<context_name>": {
      "<file>": ["<line_numbers>"]
    }
  },
  "affected_tests": ["<context_name>"]
}
```

- `coverage_summary`: line and branch coverage counts for each source file under `calclib/`. Values must match what coverage.py's analysis computes (executed statements vs total statements, covered branch exits vs total branch exits).
- `context_mapping`: maps each non-empty dynamic context to the list of source files it covers.
- `exclusive_coverage`: for each context, the lines exclusively covered by that single context — lines where no other non-empty context provides coverage. Omit contexts with no exclusive lines.
- `affected_tests`: all non-empty contexts that cover any line listed in `/app/changes.json`.

All file paths in the report must be relative to `/app/` (e.g., `calclib/core.py`).