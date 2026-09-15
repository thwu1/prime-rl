# Evaluation Pipeline Specification

## Overview

This system evaluates the relatedness between Wikipedia tables and text passages using ranked information retrieval methodology. It combines multiple scoring signals, optimizes per-method fusion weights via cross-validation, and reports standard IR evaluation metrics.

## Data Model

The system operates on three data files in `/app/data/`:

| File | Format | Schema |
|------|--------|--------|
| `tables.json` | JSON array | Each element: `{id: str, url: str, title: str, header: [str], rows: [[str]]}` |
| `texts.json` | JSON array | Each element: `{text_id: str, text: str, url: str}` |
| `pairs.csv` | CSV | Columns: `text_id`, `table_id`, `label` (binary 0/1) |

## Module API

`/app/pipeline.py` must expose the following callable functions:

### Data Functions

**`load_data(data_dir: str) -> Tuple[dict, dict, DataFrame]`**

Loads the three data files and returns `(tables_by_id, texts_by_id, pairs_df)`.
- `tables_by_id`: dict keyed by `id` field
- `texts_by_id`: dict keyed by `text_id` field
- `pairs_df`: DataFrame with columns `text_id`, `table_id`, `label` (int)

**`serialize_table(table: dict) -> str`**

Converts a table record to a flat text string. The serialized form must preserve:
- The table's **title**
- All column **header names**
- All **cell values** from every row

### Evaluation Metrics

All metric functions operate on a **binary relevance list** in descending score order (index 0 = highest-scored item).

**`compute_precision_at_k(relevance: list, k: int) -> float`**

    P@k = |{relevant items in positions 1..k}| / k

The denominator is always `k`, regardless of how many items exist in the relevance list. Positions beyond the list length are treated as irrelevant.

**`compute_recall_at_k(relevance: list, k: int, total_relevant: int) -> float`**

    R@k = |{relevant items in positions 1..k}| / total_relevant

Returns 0.0 when `total_relevant` is 0.

**`compute_f1_at_k(relevance: list, k: int, total_relevant: int) -> float`**

    F1@k = 2 * P@k * R@k / (P@k + R@k)

Returns 0.0 when both P@k and R@k are 0.

**`compute_ndcg_at_k(relevance: list, k: int, total_relevant: int) -> float`**

Normalized Discounted Cumulative Gain with binary relevance:

    DCG@k  = sum over i=0..min(k,len)-1 of: rel[i] / log2(i + 2)
    IDCG@k = sum over i=0..min(k,total_relevant)-1 of: 1 / log2(i + 2)
    NDCG@k = DCG@k / IDCG@k

Note the `log2(i + 2)` discount factor (position 0 gets discount `log2(2) = 1`, position 1 gets `log2(3)`, etc.). Returns 0.0 when `total_relevant` is 0 or IDCG is 0.

**`compute_reciprocal_rank(relevance: list) -> float`**

Returns `1 / rank` of the first relevant item, where rank is **1-indexed** (the item at list index 0 has rank 1). Returns 0.0 if no relevant item exists.

**`compute_average_precision(relevance: list) -> float`**

Average Precision for a single ranked list:

    AP = (1 / total_relevant) * sum over k=1..n of: (P@k * rel[k])

Where `total_relevant = sum(relevance)` and `P@k` is precision at position k. Only positions where `rel[k] = 1` contribute to the sum. Returns 0.0 when `total_relevant` is 0.

### Rank Fusion

**`reciprocal_rank_fusion(rankings: dict, k_rrf: int = 60, weights: dict = None) -> dict`**

Combines multiple ranked lists using weighted Reciprocal Rank Fusion.

- Input: `rankings = {method_name: [doc_ids in ranked order]}`, `weights = {method_name: weight}` (optional; defaults to uniform 1.0)
- Output: `{doc_id: score}` where `score = sum of weight[method] * 1/(k_rrf + rank)` across all rankers
- Ranks are **1-indexed**: the first item in each ranked list has rank 1
- When `weights` is None, all methods receive weight 1.0

### BM25 Scoring

**`compute_bm25_scores(tables_serialized: dict, pairs_df: DataFrame, texts_dict: dict, tables_dict: dict, k1: float = 1.5, b: float = 0.75) -> dict`**

Computes BM25 scores for all (text, table) pairs. The corpus consists of the serialized table texts. Each text passage serves as a query against the table corpus.

- Tokenization: lowercase whitespace split for both queries and documents
- IDF uses the Robertson formula: `IDF(t) = log((N - df(t) + 0.5) / (df(t) + 0.5) + 1)` where N = corpus size, df(t) = number of documents containing term t
- Term frequency scoring: `TF_component = (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avgdl))` where f = term frequency in document, dl = document length, avgdl = average document length
- Returns `{(text_id, table_id): score}`

### Cross-Validation and Weight Optimization

**`create_grouped_folds(pairs_df: DataFrame, n_folds: int = 5) -> list`**

Creates grouped k-fold splits ensuring no `text_id` appears in both train and validation within the same fold.

Assignment procedure:
1. Collect unique text_ids and **sort** them
2. Assign sorted text_ids round-robin: text_id at sorted index `i` goes to fold `i % n_folds`
3. Return `[(train_indices, val_indices)]` for each fold

Must be **deterministic** — identical inputs always produce identical fold assignments.

**`optimize_rrf_weights(method_scores: dict, pairs_df: DataFrame, folds: list, k_rrf: int = 60, k_eval: int = 10) -> dict`**

Finds optimal per-method weights for RRF via cross-validated grid search.

- Input: `method_scores = {method_name: {(text_id, table_id): score}}`, folds from `create_grouped_folds`
- Searches over a grid of weight values for each method
- Evaluates F1@k_eval on validation folds for each weight combination
- Returns `{method_name: optimal_weight}` with all weights non-negative and at least one positive

## Output Requirements

Executing `python3 /app/pipeline.py` must produce four files:

| File | Format | Required Content |
|------|--------|-----------------|
| `/app/output/metrics.json` | JSON object | Keys: `p_at_5`, `r_at_5`, `f1_at_5`, `ndcg_at_5`, `p_at_10`, `r_at_10`, `f1_at_10`, `ndcg_at_10`, `p_at_20`, `r_at_20`, `f1_at_20`, `ndcg_at_20`, `mrr`, `map`, `best_threshold` — all numeric, metrics in [0, 1] |
| `/app/output/predictions.csv` | CSV | Columns: `text_id`, `table_id`, `score` — must cover every pair from `pairs.csv`, scores in [0, 1] |
| `/app/output/config.json` | JSON object | Keys: `methods` (list of str with all 4 method names), `weights` (dict mapping method name to weight), `threshold` (float), `n_folds` (int), `k_values` (list of int) |
| `/app/output/comparison.json` | JSON object | Keys: `uniform` and `optimized`, each with `weights` (dict of method→weight) and `metrics` (dict with `f1_at_10`, `map`, `ndcg_at_10`). Uniform section uses weight 1.0 for all four methods. All metrics in [0, 1]. |
