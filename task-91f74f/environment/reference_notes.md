
# Evaluation Methodology Notes

Internal documentation recovered from the original evaluation committee.

## Challenge Structure

Multi-task evaluation across three clinical domains in head-and-neck oncology.
Four teams submitted predictions; results are combined into an overall ranking.

## 1. Tumor Segmentation — Dice Similarity Coefficient

The Dice coefficient is computed as a micro-averaged (aggregated) metric: total
intersection volume and total reference+prediction volume are summed across all
patients before computing the ratio. Two target classes (GTVp = class 1,
GTVn = class 2) are scored independently, then averaged for the final
segmentation score.

Edge case: if both total ground-truth and total prediction volume equal zero
for a class, the DSC for that class is defined as 1.0.

## 2. Pathological Staging — Balanced Accuracy

Classification performance for T-stage and N-stage is assessed using balanced
accuracy: the unweighted mean of per-class recall values. Only classes present
in the ground truth contribute. The final staging score averages the T-stage
and N-stage balanced accuracies.

## 3. Survival Prognosis — Concordance Index

The concordance index (C-index) measures ranking accuracy for survival
predictions.

- Risk scores follow the hazard convention: higher values indicate higher
  risk (shorter expected survival). The C-index computation must properly
  account for this directionality.
- Censoring: only admissible (valid) pairs contribute to the statistic.
- Missing predictions (NaN risk scores): patients with missing predictions
  remain in the pair enumeration. Any valid pair involving a NaN prediction
  is counted as a tied prediction, not excluded from analysis.

## 4. Overall Ranking

Weighted score = 0.25 x SegScore + 0.35 x StagingScore + 0.40 x PrognosisScore

Unweighted score = (SegScore + StagingScore + PrognosisScore) / 3

Consistency = |Weighted - Unweighted| (lower is better).

Primary sort: weighted score descending.
Tie-break: consistency ascending.

## 5. Bootstrap Confidence Intervals

95% percentile bootstrap: 1000 iterations, seed 42, patient-level resampling
with replacement. CI bounds at the 2.5th and 97.5th percentile values.

Report CIs for: segmentation ("seg"), staging, prognosis, and weighted scores.

## Output Schema

Write results to `/app/results.json`:

```json
{
  "teams": {
    "<team_name>": {
      "segmentation": {
        "class_1_agg_dsc": "<float>",
        "class_2_agg_dsc": "<float>",
        "mean_agg_dsc": "<float>"
      },
      "staging": {
        "balanced_accuracy_T": "<float>",
        "balanced_accuracy_N": "<float>",
        "mean_balanced_accuracy": "<float>"
      },
      "prognosis": {
        "c_index": "<float>"
      },
      "overall": {
        "segmentation_score": "<float>",
        "staging_score": "<float>",
        "prognosis_score": "<float>",
        "weighted_score": "<float>",
        "unweighted_score": "<float>",
        "consistency": "<float>",
        "rank": "<int>"
      },
      "bootstrap_ci": {
        "seg": {"lower": "<float>", "upper": "<float>"},
        "staging": {"lower": "<float>", "upper": "<float>"},
        "prognosis": {"lower": "<float>", "upper": "<float>"},
        "weighted": {"lower": "<float>", "upper": "<float>"}
      }
    }
  },
  "rankings": {
    "<team_name>": "<int>"
  }
}
```
