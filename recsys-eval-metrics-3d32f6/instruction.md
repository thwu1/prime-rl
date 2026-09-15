The evaluation system at `/app/` has two components:

1. `/app/score_converter.py` — converts raw model prediction scores into ranked-list JSON format
2. `/app/eval_tool.py` — computes recommendation metrics from ranked-list JSON

Reference source code from the framework these tools replicate is at `/app/recbole_src/`. These files define the authoritative semantics for every metric, ID convention, and data representation.

**Pre-processed evaluation (scenarios 1–3):**

Data is at `/app/data/scenario{1,2,3}/`, each containing `ranked_lists.json`, `ground_truth.json`, and `config.json`. Run directly:

    python3 /app/eval_tool.py <input_dir> <output_file>

**Score-matrix evaluation (scenarios 4–5):**

Raw model output is at `/app/data/scenario{4,5}/`, each containing `scores.json` (2D array: users × items of predicted scores), `relevance.json` (2D binary relevance matrix), and `eval_config.yaml` (YAML configuration). Run the pipeline:

    python3 /app/score_converter.py <scores_dir> <processed_dir>
    python3 /app/eval_tool.py <processed_dir> <output_file>

**Data schemas:**

- `ranked_lists.json`: `{"users": [{"user_id": int, "ranked_items": [int, ...]}, ...]}`
- `ground_truth.json`: `{"users": [{"user_id": int, "relevant_items": [int, ...]}, ...]}`
- `config.json`: `{"topk": [int, ...], "metrics": [str, ...], "num_items": int}`
- Item IDs are 1-based integers.

**Output format:** JSON at `<output_file>`: `{"<metric>@<K>": <float>, ...}`. Values rounded to 4 decimal places. Keys lowercase. Create parent directories if absent.

**Metrics:** `recall`, `precision`, `hit`, `mrr`, `ndcg`, `map`, `itemcoverage`, `giniindex`, `shannonentropy`. Metric names in config are case-insensitive. Diversity metrics (`itemcoverage`, `giniindex`, `shannonentropy`) are system-level across all users.

**Requirements:**

- Both tools contain bugs causing incorrect results. Fix all bugs so the pipeline produces numerically correct output (tolerance 1e-3) for all five scenarios and arbitrary valid inputs.
- Determine correct metric semantics by examining the reference source — the framework's conventions govern normalization, user filtering, score ranking, and catalog-level computations.
- The `score_converter.py` must correctly handle both list and scalar `topk` values in YAML configs.
- Expected outputs for scenarios 1–3 are at `/app/expected/scenario{1,2,3}.json`.

**Success criteria:** Both tools, used independently and in pipeline, produce correct results matching the reference framework's metric semantics.
