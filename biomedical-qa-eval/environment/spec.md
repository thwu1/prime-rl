# BioASQ Task B Evaluation Specification

## Overview

This document specifies the evaluation measures for a BioASQ-style biomedical question answering challenge (Task B). The evaluation pipeline computes metrics for document retrieval and three types of exact-answer questions: yes/no, factoid, and list.

## Data Format

### Golden Standard (`/app/data/golden.json`)

```json
{
  "questions": [
    {
      "id": "string",
      "type": "yesno | factoid | list",
      "body": "question text",
      "documents": ["pubmed_url_1", "pubmed_url_2", ...],
      "exact_answer": <type-dependent, see below>
    }
  ]
}
```

**exact_answer by question type:**
- **yesno**: a string, either `"yes"` or `"no"`
- **factoid**: a list of answer groups, where each group is a list of synonymous strings. Example: `[["TP53", "p53", "tumor protein p53"]]`. A system answer matches if it matches any synonym in any group (case-insensitive exact match).
- **list**: a list of items, where each item is a list of synonymous strings. Example: `[["aspirin", "ASA"], ["ibuprofen", "Advil"]]`.

### System Submissions (`/app/data/submissions/system_*.json`)

```json
{
  "system_name": "string",
  "questions": [
    {
      "id": "string",
      "documents": ["pubmed_url_1", ...],
      "exact_answer": <type-dependent, see below>
    }
  ]
}
```

**exact_answer by question type in submissions:**
- **yesno**: a string, `"yes"` or `"no"`
- **factoid**: a flat list of ranked candidate strings (up to 5). The first candidate is the system's top prediction. An empty list means the system chose not to answer.
- **list**: a flat list of submitted item strings.

## Evaluation Measures

### 1. Document Retrieval

**Modified Average Precision (AP):**

For each question, compute AP using the BioASQ-modified formula. Systems submit a ranked list of up to 10 document URLs. Let R be the set of golden relevant documents and |R| = number of relevant documents.

```
AP(q) = (1 / min(|R|, 10)) * sum_{k=1}^{n} P(k) * rel(k)
```

where:
- n = number of submitted documents (capped at 10)
- P(k) = precision at rank k = (number of relevant docs in top k) / k
- rel(k) = 1 if the document at rank k is relevant, 0 otherwise
- The denominator is `min(|R|, 10)`, NOT `|R|`

If |R| = 0 (no golden documents), AP = 0.

**Mean Average Precision (MAP):**
```
MAP = (1/Q) * sum_{q=1}^{Q} AP(q)
```
where Q is the total number of questions (all types).

**Geometric Mean Average Precision (GMAP):**
```
GMAP = (prod_{q=1}^{Q} AP'(q))^{1/Q}
```
where AP'(q) = max(AP(q), epsilon) with epsilon = 1e-5. This is equivalently computed as:
```
GMAP = exp( (1/Q) * sum_{q=1}^{Q} ln(AP'(q)) )
```
using the **natural logarithm** (ln). The epsilon prevents undefined logarithms for zero AP values.

### 2. Yes/No Questions

**Accuracy:** Fraction of correctly predicted yes/no answers (case-insensitive).

**Macro-averaged F1:** Compute F1 for each class (yes, no) separately, then take the unweighted mean.

For class c in {yes, no}:
- TP_c = number of questions where both prediction and golden answer are c
- FP_c = number of questions where prediction is c but golden answer is not c
- FN_c = number of questions where golden answer is c but prediction is not c
- P_c = TP_c / (TP_c + FP_c) if (TP_c + FP_c) > 0, else 0
- R_c = TP_c / (TP_c + FN_c) if (TP_c + FN_c) > 0, else 0
- F1_c = 2 * P_c * R_c / (P_c + R_c) if (P_c + R_c) > 0, else 0

```
macro_F1 = (F1_yes + F1_no) / 2
```

**Important:** macro_F1 is a non-decomposable metric. It cannot be computed by averaging per-question scores — it requires aggregate TP/FP/FN counts across the entire question set.

### 3. Factoid Questions

All matching is **case-insensitive exact string comparison** against any synonym in any answer group of the golden answer.

**Strict Accuracy:** Fraction of factoid questions where the system's **first** candidate matches the golden answer.

**Lenient Accuracy:** Fraction of factoid questions where **any** of the system's candidates (up to 5) matches the golden answer.

**Mean Reciprocal Rank (MRR):**
```
MRR = (1/Q_f) * sum_{q} 1/rank(q)
```
where Q_f is the **total number of factoid questions** in the golden standard, and rank(q) is the position (1-indexed) of the first correct candidate. If no candidate matches (or the system did not answer), 1/rank(q) = 0. The denominator Q_f is always the total number of factoid questions, regardless of how many the system chose to answer.

### 4. List Questions

For each list question, compare submitted items against golden items using **case-insensitive exact string matching** against all synonyms in each golden item's synonym group.

- A submitted item is **correct** if it matches any synonym of any golden item
- A golden item is **found** if at least one submitted item matches **any** of its synonyms (not just the first synonym)

```
precision(q) = (number of correct submitted items) / (number of submitted items)
recall(q) = (number of found golden items) / (number of golden items)
F1(q) = 2 * precision(q) * recall(q) / (precision(q) + recall(q))
```

If a denominator is zero, the corresponding metric is 0.

Report: mean precision, mean recall, mean F1 across all list questions.

### 5. System Ranking

The final system ranking is based on the **average rank** across the three exact-answer metrics:
1. Yes/No macro F1
2. Factoid MRR
3. List mean F1

For each metric, rank systems from best (rank 1) to worst. Ties receive the same rank (average of tied positions). The system with the lowest average rank is ranked first overall.

## 6. Bootstrap Ranking Confidence Analysis

Assess ranking stability via question-level bootstrap resampling.

**Parameters:**
- B = 1000 iterations
- RNG: `numpy.random.default_rng(seed=42)`
- A single RNG instance, used sequentially across all iterations

**Per iteration:**

1. Sort question IDs **lexicographically** within each type.
2. Sample with replacement (each to its original count), in this order: yesno questions first, then factoid, then list.
3. Recompute the three ranking metrics from the resampled questions:
   - **yesno macro_F1**: Recompute per-class TP/FP/FN counts from the resampled multiset, then compute macro F1. Duplicate questions in the sample count as separate observations. This is critical: because macro_F1 is non-decomposable, you cannot simply average per-question F1 scores.
   - **factoid MRR**: Mean reciprocal rank over the resampled factoid questions. The denominator equals the resampled set size (same as original count since we sample to the same size).
   - **list mean_F1**: Mean of per-question F1 scores over the resampled list questions.
4. Compute ranking from the 3 resampled metrics using the same procedure as Section 5 (average rank across metrics, tied ranks averaged).
5. Record each system's final rank position (with ties averaged as in Section 5).

**Report for each system:**
- `rank_ci_lower`: 2.5th percentile of the rank distribution (use `numpy.percentile` with default interpolation)
- `rank_ci_upper`: 97.5th percentile
- `prob_rank_1`: fraction of iterations where the system ranked exactly first (rank == 1.0)

Document retrieval metrics (MAP, GMAP) are NOT used in ranking and NOT bootstrapped.

## 7. Historical Database

An SQLite database at `/app/data/historical.db` contains evaluation results from prior challenge rounds. Schema:

- `rounds(round_id INTEGER PRIMARY KEY, round_name TEXT)`
- `systems(system_id INTEGER PRIMARY KEY, system_name TEXT UNIQUE)`
- `results(round_id INTEGER, system_id INTEGER, metric_name TEXT, metric_value REAL, PRIMARY KEY(round_id, system_id, metric_name))`

The `metric_name` values include: `yesno_macro_f1`, `factoid_mrr`, `list_mean_f1`, `map`, `gmap`.

### Historical Database Updates

After computing corrected results, update the database:

**Round 4 insertion:** Insert the current corrected evaluation results as round 4 ("BioASQ Round 4"). Register any new systems (delta, epsilon) not present in prior rounds. Store the same 5 metric types as prior rounds.

**View `v_metric_trends`:** For each system, metric, and round, show:
- `system_name`, `round_id`, `round_name`, `metric_name`, `metric_value`
- `prev_value`: the metric value from the previous round (NULL for the first round a system appears), using `LAG()` window function partitioned by system_name and metric_name, ordered by round_id
- `delta`: `metric_value - prev_value` (NULL when prev_value is NULL)

**View `v_current_anomalies`:** For the most recent round (highest round_id), compute z-scores against all prior rounds. Show:
- `system_name`, `metric_name`, `current_value`, `hist_mean`, `hist_std`, `z_score`
- Only include rows where the system has ≥2 prior rounds of data and `hist_std > 0`
- Compute sample standard deviation manually (SQLite lacks built-in STDEV): use the algebraic identity `sqrt((sum(x²) - sum(x)²/n) / (n-1))`
- z_score = (current_value - hist_mean) / hist_std
