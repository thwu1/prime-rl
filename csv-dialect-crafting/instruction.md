CleverCSV (`clevercsv==0.8.5`) is installed in the environment. It detects CSV dialects more accurately than Python's built-in `csv.Sniffer` by using internal scoring mechanisms that evaluate candidate delimiters, quote characters, and escape characters. Your task is to reverse-engineer CleverCSV's internal detection pipeline from its source code, build a diagnostic tool that exposes the full scoring breakdown, and craft adversarial CSV files that exercise specific edge cases in the detection logic.

## Deliverables

**`/app/score_report.py`** — A Python script that accepts a CSV file path as its only command-line argument and outputs JSON to stdout containing:
- `"candidates"`: all candidate dialects evaluated during detection, sorted by overall quality score descending. Each entry must include `"delimiter"`, `"quotechar"`, `"escapechar"`, `"pattern_score"`, `"type_score"`, `"consistency_score"`.
- `"winner"`: object with `"delimiter"`, `"quotechar"`, `"escapechar"` of the winning dialect.
- `"method"`: string identifying the internal detection pathway that produced the winner.

All scores must be extracted from CleverCSV's own internal modules — do not reimplement scoring logic.

**Four adversarial CSV files in `/app/challenges/`:**

- `pipe_consistency.csv` — CleverCSV must detect delimiter=`|`, empty quotechar, empty escapechar. The reported detection method must NOT be `"normal"`. Minimum 8 data rows, 4 columns.
- `mixed_quoting.csv` — CleverCSV must detect delimiter=`;`, quotechar=`'`. Rows must contain both quoted and unquoted cells within the same row. Minimum 6 data rows, 5 columns.
- `sniffer_disagree.csv` — Python's `csv.Sniffer().sniff()` must pick a different delimiter than CleverCSV for the same file. Minimum 6 data rows.
- `many_candidates.csv` — CleverCSV's internal candidate dialect enumeration must yield at least 20 candidate dialects for this file. Minimum 5 data rows, 3 columns.

**`/app/results.json`** — JSON object keyed by challenge filename, each value being the `score_report.py` output for that file.