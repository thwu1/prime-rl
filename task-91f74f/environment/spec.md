
# Multi-Task Clinical Challenge Evaluation Specification

This document specifies the evaluation methodology for a multi-task head-and-neck oncology challenge modeled on clinical trial evaluation pipelines. The challenge consists of three interconnected subtasks evaluated with task-specific metrics and combined via a weighted ranking scheme.

## 1. Segmentation Task — Aggregated Dice Similarity Coefficient

The segmentation metric is the **Aggregated Dice Similarity Coefficient (Aggregated DSC)**, computed per class and then averaged.

### Definition

For each class `c` in {1, 2} (1 = GTVp, 2 = GTVn):

1. For each patient `i`, the individual intersection and volume data are provided:
   - `intersection_i` = volume of intersection between prediction and ground truth (in mm³)
   - `gt_vol_i` = volume of ground truth (in mm³)
   - `pred_vol_i` = volume of prediction (in mm³)

2. The aggregated DSC for class `c` is:
   ```
   AggDSC_c = (2 * Σ_i intersection_i) / Σ_i (gt_vol_i + pred_vol_i)
   ```

3. If `Σ_i (gt_vol_i + pred_vol_i) = 0` for a class (no ground truth and no predictions for any patient), set `AggDSC_c = 1.0`.

4. The final segmentation score is the mean of class-level aggregated DSC:
   ```
   SegScore = (AggDSC_1 + AggDSC_2) / 2
   ```

**Important**: This is a micro-averaged (volume-weighted) Dice, NOT the mean of per-patient Dice scores. Larger regions contribute more to the final score.

## 2. TN Staging Task — Balanced Accuracy

The staging task is a multi-label, multi-class classification problem predicting tumor stage (T) and nodal stage (N).

### Definition

For each staging dimension (T and N):

1. Identify all classes present in the ground truth.
2. For each class, compute the per-class recall: `recall_c = TP_c / (TP_c + FN_c)` where `TP_c` is the number of patients correctly classified as class `c` and `FN_c` is the number of patients of true class `c` that were misclassified.
3. Balanced accuracy is the unweighted mean of per-class recalls:
   ```
   BA = (1/K) * Σ_c recall_c
   ```
   where K is the number of classes present in the ground truth.

4. If a class has zero ground truth samples, it is excluded from the computation.

5. The final staging score is:
   ```
   StagingScore = (BA_T + BA_N) / 2
   ```

## 3. Prognosis Task — Concordance Index

The prognosis task evaluates survival prediction using the **Concordance Index (C-index)**.

### Definition

The C-index measures the model's ability to correctly rank patients by risk.

#### Anti-concordant convention

Risk scores represent predicted hazard: **higher values indicate higher risk** (shorter expected survival). Before computing concordance, **negate the risk scores** so that the comparison convention becomes: higher transformed score ↔ longer survival.

Let `pred_i = -risk_score_i` for all patients.

#### Valid pairs

A pair (a, b) is valid (admissible) if and only if:
- `time_a ≠ time_b` and both events are observed, OR
- `time_a ≠ time_b`, exactly one event is observed, and the observed event has the shorter time, OR
- `time_a = time_b` and exactly one event is observed.

Formally:
```
valid(a, b) =
  (time_a == time_b) → (event_a ≠ event_b)
  (event_a AND event_b) → True
  (event_a AND time_a < time_b) → True
  (event_b AND time_b < time_a) → True
  otherwise → False
```

#### Concordance value

For each valid pair (a, b):
- If `pred_a` or `pred_b` is NaN (missing prediction): count as tied (0 correct, 1 tied).
- If `pred_a == pred_b`: count as tied.
- If `pred_a < pred_b`: concordant if `time_a < time_b` or (`time_a == time_b` and `event_a` and not `event_b`).
- If `pred_a > pred_b`: concordant if `time_a > time_b` or (`time_a == time_b` and not `event_a` and `event_b`).

#### Final C-index

```
C-index = (num_correct + num_tied / 2) / num_pairs
```

where `num_pairs` counts all valid pairs, `num_correct` counts concordant pairs, and `num_tied` counts tied pairs.

### Missing predictions

Some teams may have `NaN` risk scores for certain patients. These are kept in the dataset and treated as tied (non-concordant) when encountered in any valid pair.

## 4. Weighted Ranking

### Overall score

The overall score for each team is a weighted combination:
```
WeightedScore = 0.25 * SegScore + 0.35 * StagingScore + 0.40 * PrognosisScore
```

### Tie-breaking

The consistency metric is defined as:
```
UnweightedScore = (SegScore + StagingScore + PrognosisScore) / 3
Consistency = |WeightedScore - UnweightedScore|
```

Lower consistency indicates more balanced performance across subtasks.

### Ranking

Teams are ranked by:
1. **Primary**: WeightedScore descending (higher is better).
2. **Tie-breaker**: Consistency ascending (lower is better, i.e., more balanced performance breaks ties).

## 5. Bootstrap Confidence Intervals

Compute 95% confidence intervals for each metric using the bootstrap method:

1. Set random seed to **42** using Python's `random.seed(42)`.
2. Perform **1000** bootstrap iterations.
3. In each iteration:
   - Resample patients **with replacement** (same number as original). Use `random.choice(patients)` for each sample.
   - Recompute all metrics for each team using only the resampled patients' data.
4. Sort the 1000 bootstrap values.
5. The 95% CI bounds are:
   - Lower: value at index `int(0.025 * 1000)` = index 25
   - Upper: value at index `int(0.975 * 1000)` = index 975

Report CIs for: segmentation score (`seg`), staging score (`staging`), prognosis score (`prognosis`), and weighted score (`weighted`).

## Output Schema

Write `/app/results.json` with the following structure:

```json
{
  "teams": {
    "<team_name>": {
      "segmentation": {
        "class_1_agg_dsc": <float>,
        "class_2_agg_dsc": <float>,
        "mean_agg_dsc": <float>
      },
      "staging": {
        "balanced_accuracy_T": <float>,
        "balanced_accuracy_N": <float>,
        "mean_balanced_accuracy": <float>
      },
      "prognosis": {
        "c_index": <float>
      },
      "overall": {
        "segmentation_score": <float>,
        "staging_score": <float>,
        "prognosis_score": <float>,
        "weighted_score": <float>,
        "unweighted_score": <float>,
        "consistency": <float>,
        "rank": <int>
      },
      "bootstrap_ci": {
        "seg": {"lower": <float>, "upper": <float>},
        "staging": {"lower": <float>, "upper": <float>},
        "prognosis": {"lower": <float>, "upper": <float>},
        "weighted": {"lower": <float>, "upper": <float>}
      }
    }
  },
  "rankings": {
    "<team_name>": <int>,
    ...
  }
}
```
