Property-based test execution data from the Hypothesis testing framework is stored across two separate SQLite database files:

- `/data/corpus.db` — repository metadata, test node definitions, execution summaries
- `/data/corpus_test_cases.db` — per-test-case execution data including individual coverage records

These databases share referential relationships but are not pre-attached. Explore their schemas to understand the full data model, table relationships, column semantics, and which data is trustworthy for coverage analysis.

Produce `/app/analysis_report.json` — an optimization report for each repository that has valid, analyzable test execution results. Coverage for a test node is defined as the set of all unique `(file_path, line_number)` pairs exercised during its execution. Not all recorded test case outcomes represent usable execution — investigate the data status semantics to determine which records contribute to true coverage.

The report must include near-duplicate detection (pairs of nodes with coverage Jaccard similarity >= 0.75) and a minimal coverage-preserving subset. Do not use third-party similarity or hashing libraries (datasketch, sklearn, scipy.spatial). Accuracy requirements: every reported pair must have true Jaccard >= 0.55; every pair with true Jaccard >= 0.92 must be reported; estimates must be within 0.20 of exact values.

`minimal_test_set` and `removed_nodes` must exactly partition the full set of analyzed nodes per repository.

Output `/app/analysis_report.json`:

```json
{
  "repositories": {
    "<full_name>": {
      "total_nodes": <int>,
      "total_lines_covered": <int>,
      "duplicate_pairs": [{"node_a": "<node_id>", "node_b": "<node_id>", "jaccard_estimate": <float>}],
      "minimal_test_set": ["<node_id>", ...],
      "minimal_set_size": <int>,
      "removed_nodes": ["<node_id>", ...]
    }
  }
}
```