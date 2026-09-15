# HECKTOR Challenge Evaluation Protocol

## Overview

This document defines the evaluation framework for a multi-task head and neck tumor (HECKTOR) challenge. Teams submit predictions for three interconnected clinical tasks — tumor segmentation, TNM staging classification, and survival prognosis — which are evaluated against ground truth and combined into a ranked leaderboard with statistical significance analysis.

## Data Organization

### Ground Truth Segmentation
NIfTI-format (.nii.gz) volumetric masks in `/app/data/ground_truth/segmentation/`, one per patient. Voxel labels: 0 = background, 1 = GTVp (primary gross tumor volume), 2 = GTVn (nodal gross tumor volume). Not all patients have nodal disease. Voxel spacing is encoded in each file's spatial header metadata.

### Clinical Database
`/app/data/patients.db` (SQLite) — normalized relational schema containing staging classification data, survival follow-up, and additional clinical records. Multiple staging classification systems, assessment methods, and assessment dates may coexist for each patient. The authoritative staging ground truth is the most recent pathological assessment under the latest AJCC edition present in the database. The prognostic endpoint for evaluation is recurrence-free survival.

### Team Submissions
Archives in `/app/data/submissions/` — detect format from file extension. Each team's extracted directory may contain:
- `segmentation/` — NIfTI prediction masks per patient
- `staging.csv` — columns: `patient_id`, `T_stage`, `N_stage` (may be absent for some teams)
- `survival.csv` — columns: `patient_id`, `risk_score`

Predictions may be at a different spatial resolution than ground truth and must be resampled using interpolation appropriate for discrete label maps.

---

## Evaluation Metrics

### 1. Segmentation

**Aggregated Dice Similarity Coefficient (DSC)**: Use the aggregated (volume-weighted) formulation — a single DSC per label derived from cohort-level volume statistics rather than averaging per-patient scores. Physical voxel volumes accounting for anisotropic spacing must be used throughout. Compute separately for GTVp (label 1) and GTVn (label 2), then average.

**95th Percentile Hausdorff Distance (HD95)**: Symmetric surface distance at the 95th percentile, computed in physical millimeters with anisotropic voxel spacing. Compute per patient per label (only for labels present in the ground truth), average across patients per label, then average across labels.

Special cases:
- Predicted mask empty for a present ground truth label → HD95 = volume diagonal distance (sqrt of sum of squared physical dimensions)
- Both masks empty → HD95 = 0

**HD95 normalized score**: `1 / (1 + mean_hd95_mm)`

**Composite segmentation score**: `0.6 × dsc_aggregated + 0.4 × hd95_normalized`

### 2. TN Staging

Balanced accuracy computed independently for T and N categories against the staging ground truth, then averaged. A team that omits staging predictions entirely receives a staging score of zero.

### 3. Prognosis

Harrell's concordance index (C-index) evaluating the discriminative ability of predicted risk scores against observed survival times, with appropriate handling of censored observations. Risk scores encoded as NaN represent missing predictions and should be penalized (treated as non-concordant). If no comparable pairs exist, C-index = 0.5.

---

## Scoring and Ranking

**Weighted score**: `0.25 × segmentation_score + 0.35 × staging_score + 0.40 × prognosis_score`

Rank teams by descending weighted score. Tie-breaker: consistency metric = `|weighted_score − mean(segmentation_score, staging_score, prognosis_score)|` (lower = better, favoring balanced performance across subtasks).

---

## Statistical Analysis

Pairwise bootstrap 95% confidence intervals for all team pairs:
- 1000 bootstrap iterations, random seed 123
- Each iteration: resample patients with replacement (same indices across both teams being compared), recompute the full composite weighted score for each team on the resampled cohort
- 95% CI from the sorted array of 1000 score differences: indices [25, 974] (0-indexed)
- A difference is significant if the entire CI excludes zero

---

## Output Format

Produce `/app/results/leaderboard.json`:

```json
{
  "rankings": [
    {
      "team": "<team_name>",
      "rank": 1,
      "dsc_aggregated": 0.XXXX,
      "hd95_mean_mm": X.XXXX,
      "hd95_normalized": 0.XXXX,
      "segmentation_score": 0.XXXX,
      "staging_score": 0.XXXX,
      "prognosis_score": 0.XXXX,
      "weighted_score": 0.XXXX,
      "consistency_score": 0.XXXX
    }
  ],
  "statistical_analysis": {
    "pairwise_comparisons": [
      {
        "team_a": "<team_name>",
        "team_b": "<team_name>",
        "ci_lower": -0.XXXX,
        "ci_upper": 0.XXXX,
        "significant": true
      }
    ]
  }
}
```

`rankings` sorted by rank (1 = best). All numeric values with at least 4 decimal places of precision.
