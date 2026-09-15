Five buggy C programs are in `/app/subjects/`. Each subject directory contains:

- `buggy.c` -- source code with exactly one single-line defect
- `test_driver.c` -- a test harness that prints `PASS: test_N` or `FAIL: test_N` per test case and accepts an optional test index argument to run a single test
- `Makefile` -- builds `test_driver` from `buggy.c` and `test_driver.c`, supports `CFLAGS` override for instrumentation

Build an automated program repair tool at `/app/repair.py` that locates and fixes single-line defects in C programs using their accompanying test suites.

When invoked as `python3 /app/repair.py` (no arguments), the tool must repair every subject in `/app/subjects/`. When invoked as `python3 /app/repair.py <subject_dir>`, it must repair the single specified subject.

For each successfully repaired subject, produce two files in that subject's directory:

- `fixed.c` -- the repaired source where every test case passes
- `repair.json` -- a JSON object with keys `line` (int, 1-indexed line that was changed), `original` (str, original line content), `fixed` (str, repaired line content)

The tool will be evaluated against additional subjects not present in the initial environment, so it must generalize beyond the provided five.