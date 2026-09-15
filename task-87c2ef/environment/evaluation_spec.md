# Multi-Task Clinical Challenge Evaluation Specification

## Overview

This evaluation system ranks **6 teams** across three interconnected clinical
tasks.  Each task is scored independently, then task-level rankings are combined
into an overall leaderboard using weighted Borda aggregation.

Teams are listed in `/app/data/submissions/`.  Each subdirectory may contain up
to three CSV files: `segmentation.csv`, `survival.csv`, `staging.csv`.  A
missing file means the team did not submit for that task.

---

## 1  Segmentation Task

Pre-computed per-patient overlap statistics are stored in each team's
`segmentation.csv` with columns:

    patient_id, tp_gtvp, vol_sum_gtvp, tp_gtvn, vol_sum_gtvn,
    tp_detect, fp_detect, fn_detect

Where:
- `tp_gtvp`  = true-positive volume (intersection) for the primary tumor (GTVp)
- `vol_sum_gtvp` = sum of ground-truth and predicted volumes for GTVp
- `tp_gtvn`, `vol_sum_gtvn` = same for lymph-node tumors (GTVn)
- `tp_detect`, `fp_detect`, `fn_detect` = lesion-level detection counts for
  GTVn (pre-computed at IoU > 30 %)

Ground-truth metadata is in `/app/data/ground_truth/segmentation_meta.csv`
with columns `patient_id, has_gtvn, n_gtvn_lesions`.

### 1.1  GTVp — Mean Dice Similarity Coefficient

For each patient *i*:

    DSC_i = 2 · TP_gtvp_i  /  vol_sum_gtvp_i        if vol_sum_gtvp_i > 0
    DSC_i = 1.0                                       if vol_sum_gtvp_i = 0

**GTVp score = (1/N) Σ DSC_i**   (arithmetic mean over all N patients)

### 1.2  GTVn — Aggregated Dice Similarity Coefficient

**IMPORTANT:** this is **not** the mean of per-patient DSC values.  It
accumulates numerator and denominator across all patients before dividing:

    GTVn_seg = 2 · Σ_i TP_gtvn_i  /  Σ_i vol_sum_gtvn_i

If Σ vol_sum_gtvn_i = 0, set GTVn_seg = 1.0.

### 1.3  GTVn — Aggregated F1-Score (detection)

    F1_agg = 2 · Σ TP_det  /  (2 · Σ TP_det + Σ FP_det + Σ FN_det)

Summations run over all patients.  If the denominator is 0, set F1_agg = 1.0.

### 1.4  Handling missing segmentation submissions

If a team has no `segmentation.csv`:

- GTVp mean DSC = 0   (every patient's prediction is empty → DSC = 0)
- GTVn aggregated DSC = 0
- GTVn aggregated F1 = 0   (TP = 0, FP = 0, FN = Σ n_gtvn_lesions from
  ground-truth metadata)

### 1.5  Segmentation ranking — multi-level Borda count

1. Rank all teams by GTVp mean DSC (higher = better) → **gtvp_rank**
2. Rank all teams by GTVn aggregated DSC (higher = better) → **gtvn_seg_rank**
3. Rank all teams by GTVn aggregated F1 (higher = better) → **gtvn_det_rank**
4. GTVn Borda score = gtvn_seg_rank + gtvn_det_rank   → **gtvn_borda**
5. Rank teams by GTVn Borda score (lower = better)     → **gtvn_borda_rank**
6. Segmentation Borda score = gtvp_rank + gtvn_borda_rank → **seg_borda**
7. Rank teams by Segmentation Borda (lower = better)   → **seg_rank**

**Tie handling in every sub-ranking:**  when two or more teams share the same
score, assign each the average of the ranks they span.  
Example: scores `[0.9, 0.8, 0.8, 0.7]` → ranks `[1.0, 2.5, 2.5, 4.0]`.

---

## 2  Survival Prognosis — Concordance Index

Each team's `survival.csv` contains `patient_id, predicted_risk`.
Ground truth is `/app/data/ground_truth/survival.csv` with columns
`patient_id, event_time, event_observed` (1 = event occurred, 0 = censored).

The predicted risk is a *risk score*: higher values indicate worse prognosis
(shorter expected survival).  **Negate the risk scores** before computing
concordance (i.e., use `score = −predicted_risk` internally).

### 2.1  Pair admissibility

For patients *a* and *b* (a < b in iteration order):

| Condition | Admissible? |
|-----------|-------------|
| time_a = time_b  **and**  event_a = event_b | No |
| time_a = time_b  **and**  event_a ≠ event_b | Yes |
| Both uncensored (event_a = event_b = 1) | Yes |
| event_a = 1  **and**  time_a < time_b | Yes |
| event_b = 1  **and**  time_b < time_a | Yes |
| Otherwise | No |

### 2.2  Concordance value

For each admissible pair, using negated scores `s = −risk`:

- If either score is **missing** (empty string in CSV): count the pair as
  **tied** (0 correct, 1 tied).
- If s_a = s_b: tied (0 correct, 1 tied).
- If s_a < s_b: concordant if `time_a < time_b`, or if
  `time_a = time_b and event_a and not event_b`.
- If s_a > s_b: concordant if `time_a > time_b`, or if
  `time_a = time_b and not event_a and event_b`.

### 2.3  Final C-index

    C = (num_concordant + num_tied / 2) / num_admissible_pairs

If no admissible pairs exist, C = 0.5.

---

## 3  TN Staging — Balanced Accuracy

Each team's `staging.csv` has `patient_id, predicted_t, predicted_n`.
Ground truth is `/app/data/ground_truth/staging.csv` with `patient_id,
t_stage, n_stage`.

### 3.1  Per-class recall

For each class *c* present in the ground truth:

    recall_c = (# patients with true label c AND predicted label c) /
               (# patients with true label c)

Classes not represented in ground truth are excluded.

### 3.2  Balanced accuracy

    BA = mean of per-class recalls

Compute separately for T-staging (classes T1–T4) and N-staging (classes N0–N3).

    mean_balanced_accuracy = (T_BA + N_BA) / 2

---

## 4  Overall Ranking

### 4.1  Task-level ranks

- **seg_rank** — from Borda segmentation (Section 1.5, step 7)
- **stage_rank** — rank teams by mean balanced accuracy (higher = better)
- **prog_rank** — rank teams by C-index (higher = better)

### 4.2  Weighted aggregation

    weighted_score = 0.25 × seg_rank + 0.35 × stage_rank + 0.40 × prog_rank

### 4.3  Tie-breaking — consistency metric

    unweighted_score = (seg_rank + stage_rank + prog_rank) / 3
    consistency = |weighted_score − unweighted_score|

Sort teams by:
1. `weighted_score` ascending (lower = better)
2. `consistency` ascending (tie-breaker; lower = more consistent)

Assign `final_rank` starting at 1.

---

## 5  Bootstrap Confidence Intervals

Create a `numpy.random.RandomState(12345)` instance and use it for all
sampling.  Perform **1000** iterations.

Each iteration:
1. Sample *N* patient indices with replacement (N = total number of patients)
   using `rng.choice(N, size=N, replace=True)` where `rng` is the RandomState.
2. For each team, recompute on the bootstrap sample:
   - GTVp mean DSC
   - GTVn aggregated DSC
   - C-index
   - Mean balanced accuracy

Report the 95 % confidence interval as
`[2.5th percentile, 97.5th percentile]` of the 1000 bootstrap values.

---

## 6  Output Format

Write the final result to `/app/output/leaderboard.json` with this schema:

```json
{
  "team_metrics": {
    "<team_name>": {
      "gtvp_mean_dsc": <float>,
      "gtvn_agg_dsc": <float>,
      "gtvn_agg_f1": <float>,
      "c_index": <float>,
      "t_balanced_accuracy": <float>,
      "n_balanced_accuracy": <float>,
      "mean_balanced_accuracy": <float>
    }
  },
  "rankings": {
    "<team_name>": {
      "gtvp_rank": <float>,
      "gtvn_seg_rank": <float>,
      "gtvn_det_rank": <float>,
      "gtvn_borda": <float>,
      "gtvn_borda_rank": <float>,
      "seg_borda": <float>,
      "seg_rank": <float>,
      "prog_rank": <float>,
      "stage_rank": <float>,
      "weighted_score": <float>,
      "consistency": <float>,
      "final_rank": <int>
    }
  },
  "final_ranking": ["<1st_place_team>", "<2nd_place_team>", "..."],
  "bootstrap_ci": {
    "<team_name>": {
      "gtvp_mean_dsc": [<lower>, <upper>],
      "gtvn_agg_dsc": [<lower>, <upper>],
      "c_index": [<lower>, <upper>],
      "mean_balanced_accuracy": [<lower>, <upper>]
    }
  }
}
```

All float values must be rounded to **6 decimal places**.
