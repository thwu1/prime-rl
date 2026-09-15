
# HN-Onc-Eval-2026: Evaluation Methodology

Committee documentation for the multi-task head-and-neck oncology challenge.

## Challenge Structure

Four teams submitted predictions across three clinical domains. Results are
combined into an overall ranking using weighted aggregation.

## 1. Tumor Segmentation — Dice Similarity Coefficient

The Dice coefficient is computed as a **micro-averaged (aggregated)** metric:
sum total intersection volume and total (ground-truth + prediction) volume
across all patients for each class, then compute a single DSC ratio per class.
Two target structures (GTVp = class 1, GTVn = class 2) are scored independently,
then averaged for the final segmentation score.

Edge case: if both total ground-truth volume and total prediction volume equal
zero for a given class across all patients, the DSC for that class is 1.0.

## 2. Pathological Staging — Balanced Accuracy

Classification performance for T-stage and N-stage is assessed using **balanced
accuracy**: the unweighted mean of per-class recall values. Only classes present
in the ground truth contribute to the calculation. The final staging score
averages the T-stage and N-stage balanced accuracies.

## 3. Survival Prognosis — Concordance Index

The concordance index (C-index) measures ranking accuracy for survival
predictions.

### 3.1 Risk Score Convention

Risk scores follow the **hazard convention**: higher values indicate higher risk
(shorter expected survival). The C-index computation must properly account for
this directionality when determining whether a pair is concordant.

### 3.2 Admissible Pairs

Only admissible (valid) pairs contribute to the C-index:
- Both events observed: always admissible
- One event, one censored: admissible only if the event time is shorter
- Both censored: never admissible
- Same event time, same event status: not admissible

### 3.3 Handling Missing Predictions

**[COMMITTEE NOTE — UNRESOLVED]**

Two approaches were benchmarked for patients with missing (NaN) risk scores:

**Approach A (Exclusion):** Remove all patients with NaN predictions from the
analysis before computing any pairs. The C-index reflects only patients with
valid predictions. This yields higher C-index values for teams with missing
data because the dropped patients are typically harder cases.

**Approach B (Penalty):** Retain all patients in the pair enumeration. When a
pair involves one or more NaN predictions, count it as a **tied prediction**
(contributing 0.5 per such pair to the concordance numerator). This penalizes
teams for failing to produce predictions.

The committee benchmarked both approaches on pilot data. **The final adopted
policy is the one consistent with the validated reference values in
audit.json.** Implementers must evaluate both approaches against the audit
spot-checks to determine the correct methodology.

## 4. Overall Ranking

Weighted score = 0.25 × SegScore + 0.35 × StagingScore + 0.40 × PrognosisScore

Unweighted score = (SegScore + StagingScore + PrognosisScore) / 3

Consistency = |Weighted − Unweighted| (lower is better).

Primary sort: weighted score descending.
Tie-break: consistency ascending.

## 5. Bootstrap Confidence Intervals

95% percentile bootstrap with **patient-level** resampling with replacement.
Parameters are specified in eval_config.toml: iteration count, random seed, and
percentile bounds.

Report CIs for: segmentation ("seg"), staging, prognosis, and weighted scores.

## 6. Rank Stability Analysis

Assess robustness of team rankings via bootstrap rank distributions. Parameters
(iteration count, seed) are specified in eval_config.toml under [rank_stability].

For each bootstrap iteration:
1. Resample patients with replacement
2. Recompute all metrics and weighted scores for all teams
3. Rank teams by weighted score (descending)

Report:
- **rank_probability_matrix**: For each team, the probability of achieving
  each rank (1 through N_teams). Keyed as team → rank_string → probability.
- **dominant_rank**: The most probable rank for each team.
- **rank_certainty**: The probability mass of the dominant rank.
- **pairwise_dominance**: P(team_i scores strictly higher than team_j) for
  all ordered pairs. Self-comparisons are 0.5.

## 7. Output Schema

### results.json

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
  "rankings": {"<team_name>": "<int>"}
}
```

### stability.json

```json
{
  "rank_probability_matrix": {
    "<team>": {"1": "<float>", "2": "<float>", ...}
  },
  "dominant_rank": {"<team>": "<int>"},
  "rank_certainty": {"<team>": "<float>"},
  "pairwise_dominance": {
    "<team_i>": {"<team_j>": "<float>", ...}
  }
}
```
