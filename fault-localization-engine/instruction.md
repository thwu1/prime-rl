`/app/subjects/` contains four directories. Each holds a buggy Python module (`program.py`) and a corresponding test suite (`test_program.py` with pytest-convention `test_` functions importing from `program`). Some tests in each suite fail due to a single-line defect in `program.py`.

Build `/app/autorepair.py` — a command-line tool that automatically diagnoses and repairs such defects. It must be syntactically valid Python. When invoked as:

```
python3 /app/autorepair.py <subject_dir>
```

it must exit with return code 0 and write results to `/app/output/<subject_name>/` (where `<subject_name>` is the basename of the subject directory). Three output files are required:

- `diagnosis.json` — JSON object with a single key `"suspicious_lines"` whose value is a list of objects, each with `"line"` (int, 1-indexed source line in `program.py`) and `"score"` (float in `[0.0, 1.0]`). The list must be sorted by score descending and contain at least 3 entries. The actual defective line must appear within the top 5 entries.

- `program_fixed.py` — a corrected version of `program.py` that passes every test in `test_program.py` when run via `pytest`.

- `repair.patch` — a non-empty unified diff between the original and fixed `program.py` (with `---`, `+++`, and `@@` headers). The diff must contain no more than 6 changed lines (lines starting with `+` or `-`, excluding `---`/`+++` headers), corresponding to at most 3 modified source lines.

The tool must generalize to arbitrary novel subjects following the same convention (a directory with `program.py` and `test_program.py`) — not just the four provided.