# PaperBench Evaluation System — Specification

## Overview

PaperBench evaluates research paper replication quality using hierarchical rubrics. Each rubric is a tree of assessment criteria. Leaves represent atomic pass/fail checks; internal nodes aggregate child scores reflecting their relative importance.

## Data Formats

### Rubric Tree (JSON)

Each node has:
- `id` (string): unique identifier
- `requirements` (string): what this criterion assesses
- `weight` (positive number): relative importance among siblings
- `sub_tasks` (array): child nodes; empty for leaf nodes

Leaf nodes also have `task_category`: one of `"Code Development"`, `"Execution"`, or `"Result Match"`.

### Grade File (JSON)

A flat object mapping leaf `id` → binary score (0 or 1).

## CLI Subcommands

The tool uses argparse with the following subcommands. All output is JSON to stdout.

---

### `score`

**Arguments:** `--rubric PATH --grades PATH`

Computes the replication score for a graded rubric. Each leaf's score is its grade (0 or 1). Each internal node's score is the weighted mean of its children's scores, where each child contributes in proportion to its `weight` relative to the total weight of all siblings at that level. The root node's score is the overall replication score.

**Output:** `{"replication_score": <float>}`

---

### `prune-score`

**Arguments:** `--rubric PATH --grades PATH --depth D`

Evaluates a rubric with depth-limited aggregation. The root is at depth 0. For nodes at depth strictly less than D, weighted aggregation (as in `score`) is applied normally. Any non-leaf node **at depth D or deeper** is "collapsed": rather than weighted aggregation, its score is the unweighted arithmetic mean of all its descendant leaves' grades, treating each leaf equally regardless of weight.

The pruning approximation error is not necessarily monotonically decreasing with depth — a shallower cut can sometimes yield a better approximation than a deeper one, depending on the weight distribution.

**Output:** `{"pruned_score": <float>, "full_score": <float>, "absolute_error": <float>}`

where `full_score` is the unpruned replication score and `absolute_error = |pruned_score - full_score|`.

---

### `optimal-depth`

**Arguments:** `--rubrics-dir DIR --grades-dir DIR --epsilon E`

Finds the minimum integer depth D >= 1 such that the pruning absolute error is at most epsilon for **every** rubric/grade pair in the directories (matched by filename). Reports both the optimal depth and the worst-case (maximum) error across all pairs at that depth.

Because the pruning error landscape is non-monotonic, all candidate depths must be checked exhaustively.

**Output:** `{"optimal_depth": <int>, "max_error": <float>}`

---

### `judge-eval`

**Arguments:** `--rubric PATH --ground-truth PATH --predicted PATH`

Evaluates an automated grading judge by comparing its predicted grades against human ground truth. Reports standard binary classification metrics per `task_category` in the rubric:

- **Precision** = TP / (TP + FP); defined as 0 when TP + FP = 0
- **Recall** = TP / (TP + FN); defined as 0 when TP + FN = 0
- **F1** = harmonic mean of precision and recall = 2*P*R / (P + R); defined as 0 when P + R = 0

Also computes the macro average of precision, recall, and F1 across all categories.

**Output:** `{"per_category": {"<category>": {"precision": <float>, "recall": <float>, "f1": <float>}, ...}, "macro_average": {"precision": <float>, "recall": <float>, "f1": <float>}}`

---

### `sensitivity`

**Arguments:** `--rubric PATH --grades PATH`

Computes the effective weight of each leaf in the rubric — defined as the absolute change in the replication score that would result from flipping that single leaf's grade (0->1 or 1->0), holding all other grades fixed. This value depends only on the rubric's tree structure and weights, not on the actual grades.

For any valid rubric, the sum of all leaf sensitivities equals exactly 1.0.

**Output:** `{"sensitivities": {"<leaf_id>": <float>, ...}}`

---

### `stratified-score`

**Arguments:** `--rubric PATH --grades PATH`

Decomposes the replication score by `task_category`. For each category c, computes:

- **contribution_c** = sum over all leaves in category c of: sensitivity(leaf) * grade(leaf)

  where sensitivity(leaf) is the effective weight of the leaf as defined in the `sensitivity` subcommand — i.e., the product of (weight / sibling_total_weight) along the root-to-leaf path.

- **coverage_c** = sum over all leaves in category c of: sensitivity(leaf)

  This is the maximum possible contribution from this category (achieved when all leaves score 1).

- **conditional_score_c** = contribution_c / coverage_c if coverage_c > 0, else 0.0

  The category-specific score, independent of the category's structural weight in the rubric.

The sum of all category contributions equals the total replication score.

**Output:** `{"categories": {"<category>": {"contribution": <float>, "coverage": <float>, "conditional_score": <float>}, ...}, "total_score": <float>}`

---

### `agreement`

**Arguments:** `--rubric PATH --predictions-dir DIR`

Computes inter-rater agreement among multiple automated judges using Fleiss' kappa. The predictions directory contains JSON files, each mapping leaf IDs to binary grades (0 or 1) from a different judge. The rubric is used to determine the set of leaf IDs and their task categories.

**Fleiss' kappa** for n subjects rated by N raters into k = 2 categories (0 and 1):

1. For each subject i, let n_{i,j} be the number of raters who assigned category j (j in {0, 1}).
2. P_i = (1 / (N * (N - 1))) * sum_j(n_{i,j} * (n_{i,j} - 1))
3. P_bar = (1 / n) * sum_i(P_i)
4. p_j = (1 / (n * N)) * sum_i(n_{i,j})
5. P_e = sum_j(p_j^2)
6. kappa = (P_bar - P_e) / (1 - P_e)

If P_e = 1 (all marginals concentrated in one category), define kappa = 1.0 if P_bar = 1 (perfect agreement), else kappa = 0.0.

Computes kappa for all leaves (overall) and separately for leaves in each `task_category` (per-category).

**Output:** `{"overall_kappa": <float>, "per_category": {"<category>": {"kappa": <float>}, ...}, "num_raters": <int>, "num_subjects": <int>}`

---

### `score-bounds`

**Arguments:** `--rubric PATH --grades PATH --uncertain IDS`

where IDS is a comma-separated list of leaf IDs whose grades are considered uncertain.

Computes the tightest possible bounds on the replication score when any subset of the specified uncertain leaves' grades may be independently flipped (0→1 or 1→0), while all other grades remain fixed. The bounds must be exact: they correspond to the minimum and maximum scores achievable over all 2^|uncertain| possible grade assignments for the uncertain set.

**Output:** `{"current_score": <float>, "min_score": <float>, "max_score": <float>, "max_swing": <float>}`

where `max_swing = max_score - min_score`.

---

## Analysis Pipeline

The analysis pipeline is a Bash shell script at `/app/analyze.sh` that uses `jq` for JSON processing and `sqlite3` for persistent storage.

The script must:

1. Create a SQLite database at `/app/results.db` with the following tables:
   - `scores(paper TEXT PRIMARY KEY, leaf_count INTEGER, score REAL)`
   - `stratified(paper TEXT, category TEXT, contribution REAL, coverage REAL, conditional_score REAL, PRIMARY KEY(paper, category))`
   - `optimal_depths(epsilon REAL PRIMARY KEY, depth INTEGER, max_error REAL)`
   - `bounds(paper TEXT PRIMARY KEY, current_score REAL, min_score REAL, max_score REAL, max_swing REAL)`

2. For each rubric/grade pair in `/app/data/rubrics/` and `/app/data/grades/` (matched by filename):
   a. Use `jq` to validate that the rubric JSON has required top-level fields (`id`, `weight`, `sub_tasks`)
   b. Use `jq` to count the number of leaf nodes (nodes with empty `sub_tasks` arrays) in the rubric
   c. Run `rubric_engine.py score` to compute the replication score
   d. Insert paper name (filename without .json extension), leaf count, and score into the `scores` table
   e. Run `rubric_engine.py stratified-score` to compute per-category breakdowns
   f. Use `jq` to parse the stratified output and insert rows into the `stratified` table
   g. Use `jq` to extract the IDs of all leaf nodes with `task_category` equal to `"Result Match"` from the rubric
   h. Run `rubric_engine.py score-bounds` with those IDs as the `--uncertain` argument (comma-separated)
   i. Insert paper name and score-bounds results into the `bounds` table

3. For each epsilon in {0.06, 0.04, 0.025, 0.01}:
   a. Run `rubric_engine.py optimal-depth` with the specified epsilon
   b. Insert the result into the `optimal_depths` table
