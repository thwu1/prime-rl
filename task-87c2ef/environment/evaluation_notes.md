# Evaluation Framework — Multi-Task Clinical Challenge

## Overview

Six teams are evaluated across three clinical tasks. Each task is scored
independently, then task-level rankings are combined into an overall
leaderboard through weighted Borda aggregation.

Submission data and ground truth are stored in the SQLite database at
`/app/data/challenge.db` (CSV exports also available under `/app/data/`).

## Database Schema

```
ground_truth_staging(patient_id, t_stage, n_stage)
ground_truth_survival(patient_id, event_time, event_observed)
segmentation_meta(patient_id, has_gtvn, n_gtvn_lesions)
submissions_segmentation(team, patient_id, tp_gtvp, vol_sum_gtvp,
    tp_gtvn, vol_sum_gtvn, tp_detect, fp_detect, fn_detect)
submissions_survival(team, patient_id, predicted_risk)
submissions_staging(team, patient_id, predicted_t, predicted_n)
```

## Task 1: Tumor Segmentation

Teams submitted pre-computed overlap statistics for primary tumor (GTVp)
and lymph node metastases (GTVn).

**GTVp** is assessed using the arithmetic mean of per-patient Dice
Similarity Coefficient:
- Per-patient DSC = 2 * TP / volume_sum (when volume_sum > 0, else 1.0)

**GTVn** requires a volume-aware assessment methodology appropriate for
structures with high inter-patient size variability, as recommended in the
medical image segmentation literature for multi-instance regional evaluation.
The approach should prevent small lesions from being overweighted in the
population-level score.

**GTVn detection** uses an aggregated F1-score across the patient cohort.

Teams that did not submit segmentation predictions should receive zero for
all segmentation sub-metrics, reflecting complete absence of predictions
against the actual ground truth lesion burden.

### Segmentation Ranking (multi-level Borda)

1. Rank teams by GTVp DSC (higher = better) -> gtvp_rank
2. Rank teams by GTVn DSC (higher = better) -> gtvn_seg_rank
3. Rank teams by GTVn F1 (higher = better) -> gtvn_det_rank
4. gtvn_borda = gtvn_seg_rank + gtvn_det_rank
5. Rank by gtvn_borda (lower = better) -> gtvn_borda_rank
6. seg_borda = gtvp_rank + gtvn_borda_rank
7. Rank by seg_borda (lower = better) -> seg_rank

All sub-rankings must use fractional averaging for tied scores.
Example: scores [0.9, 0.8, 0.8, 0.7] -> ranks [1.0, 2.5, 2.5, 4.0].

## Task 2: Survival Prognosis (C-index)

Teams provided predicted risk scores for each patient. Higher predicted_risk
indicates worse expected prognosis. Evaluation uses the concordance index
with proper handling of censored observations. Standard biostatistical
conventions for risk-score orientation and pair comparability under
censoring apply.

Missing predictions (NULL or empty) should be treated as non-informative
(counted as tied with any comparison partner).

## Task 3: TN Staging (Balanced Accuracy)

Balanced accuracy = mean per-class recall, computed separately for
T-staging (T1-T4) and N-staging (N0-N3).

Combined staging score = (T_BA + N_BA) / 2

## Overall Ranking

Task-level ranks are combined with weights specified in
`/app/evaluator/config.toml`:

    weighted_score = w_seg * seg_rank + w_stg * stage_rank + w_prog * prog_rank

Tie-breaking uses a consistency metric:

    unweighted = (seg_rank + stage_rank + prog_rank) / 3
    consistency = |weighted_score - unweighted|

Sort ascending by weighted_score, then by consistency (lower = better).

## Bootstrap Confidence Intervals

Patient-level resampling with replacement. Parameters (iterations, seed)
are specified in the pipeline configuration file. Report
[2.5th percentile, 97.5th percentile].

## Output Schema

Write to the path specified in the configuration:

```json
{
  "team_metrics": {
    "<team>": {
      "gtvp_mean_dsc": "<float>",
      "gtvn_agg_dsc": "<float>",
      "gtvn_agg_f1": "<float>",
      "c_index": "<float>",
      "t_balanced_accuracy": "<float>",
      "n_balanced_accuracy": "<float>",
      "mean_balanced_accuracy": "<float>"
    }
  },
  "rankings": {
    "<team>": {
      "gtvp_rank": "<float>",
      "gtvn_seg_rank": "<float>",
      "gtvn_det_rank": "<float>",
      "gtvn_borda": "<float>",
      "gtvn_borda_rank": "<float>",
      "seg_borda": "<float>",
      "seg_rank": "<float>",
      "prog_rank": "<float>",
      "stage_rank": "<float>",
      "weighted_score": "<float>",
      "consistency": "<float>",
      "final_rank": "<int>"
    }
  },
  "final_ranking": ["1st_place", "2nd_place", "..."],
  "bootstrap_ci": {
    "<team>": {
      "gtvp_mean_dsc": ["<lo>", "<hi>"],
      "gtvn_agg_dsc": ["<lo>", "<hi>"],
      "c_index": ["<lo>", "<hi>"],
      "mean_balanced_accuracy": ["<lo>", "<hi>"]
    }
  }
}
```

All float values rounded to 6 decimal places.
