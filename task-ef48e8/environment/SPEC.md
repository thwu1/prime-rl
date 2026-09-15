# Clinical Evidence Evaluation Framework — Specification

## 1. Overview

This framework evaluates system outputs for two clinical NLP tasks:

- **Evidence Identification**: Given a clinical question and a note excerpt, identify
  which sentences in the note are evidence for the answer.
- **Evidence-Answer Alignment**: Given answer sentences and note sentences, identify
  which evidence sentences support each answer sentence.

The framework handles multi-annotator gold data stored in a SQLite database,
requiring adjudication before scoring. An R-based cross-validation module
independently verifies the inter-annotator agreement computation.

## 2. Data Sources

### SQLite Database (`data/annotations.db`)

Gold annotation data is stored in a normalized SQLite database with the following
schema:

- `cases(case_id TEXT PRIMARY KEY)`
- `note_sentences(case_id, sentence_id, sentence_text)`
- `answer_sentences(case_id, answer_id, answer_text)`
- `answer_citations(case_id, answer_id, evidence_id)`
- `annotator_labels(case_id, annotator_id, sentence_id, relevance)`

The `relevance` column contains one of: `essential`, `supplementary`, `not-relevant`.

A CSV export of annotator labels is also available at `data/annotator_labels.csv`.

### Submissions (JSON)

Evidence Identification Submission (`data/submission_evidence.json`):
```json
[{"case_id": "1", "prediction": ["s1", "s4"]}]
```

Evidence Alignment Submission (`data/submission_alignment.json`):
```json
[{"case_id": "1", "prediction": [{"answer_id": "a1", "evidence_id": ["s1", "s2"]}]}]
```

## 3. Adjudication Protocol

Multi-annotator labels are resolved into a single gold standard per sentence:

1. **Relevance determination**: Count annotators who labeled the sentence as either
   "essential" or "supplementary". If this count is **greater than or equal to** the
   threshold (default: 2), the sentence is deemed relevant.

2. **Relevance tier assignment**: Among the annotators who labeled the sentence as
   relevant, if a **strict majority** labeled it "essential" (i.e., essential count >
   relevant count / 2), it is classified as **essential**. Otherwise, it is classified
   as **supplementary**.

3. If the relevance count is below the threshold, the sentence is "not-relevant".

This produces two evidence sets per case:
- **Strict evidence**: sentences adjudicated as "essential"
- **Lenient evidence**: sentences adjudicated as "essential" OR "supplementary"

## 4. Evidence Identification Scoring

### 4.1 Strict Scoring

Standard set-based precision/recall/F1:
- **Predicted set** = submitted evidence sentence IDs
- **Gold set** = strict evidence (essential only)
- P = |predicted ∩ gold| / |predicted|
- R = |predicted ∩ gold| / |gold|
- F1 = 2PR / (P + R)

### 4.2 Lenient Scoring

In lenient mode, predicting supplementary sentences is not penalized. The procedure:

1. Compute the set of **supplementary-only** sentence IDs:
   `supplementary_only = lenient_evidence − strict_evidence`
2. **Filter** the prediction set by removing supplementary-only predictions:
   `filtered_predicted = predicted − supplementary_only`
3. Score `filtered_predicted` against `strict_evidence` (essential only) using P/R/F1.

This means:
- Predicting an essential sentence contributes to TP.
- Predicting a supplementary sentence has no effect (removed from predictions).
- Predicting a non-relevant sentence reduces precision.

### 4.3 Aggregation

- **Micro-averaged**: Pool TP, predicted count, and gold count across all cases, then
  compute P/R/F1 from the pooled counts.
- **Macro-averaged**: Compute P/R/F1 per case, then average across cases.

## 5. Bootstrap Confidence Intervals

Bootstrap CIs are computed for the **micro-averaged F1** scores (both strict and
lenient).

Parameters: n_bootstrap=2000, seed=42, confidence=0.95.

The resampling unit is the **case**: each bootstrap iteration draws N cases with
replacement (where N = total number of cases). The CI bounds are the 2.5th and
97.5th percentiles of the bootstrap distribution.

The bootstrap must produce a distribution of **micro F1** values. Each iteration
should pool the raw per-case counts (TP, predicted count, gold count) from the
resampled cases and compute micro P/R/F1 from the pooled totals. This is distinct
from resampling per-case F1 values and averaging, which would produce a CI for
*macro* F1 rather than micro F1.

## 6. Evidence-Answer Alignment Scoring

### 6.1 Standard (Unweighted) Alignment

Each alignment is a pair (answer_sentence_id, evidence_sentence_id).

- Gold alignments come from the `citations` field in `answer_sentences`.
- Predicted alignments are extracted from the submission.
- Standard P/R/F1 treats all correct alignment pairs equally.

Micro and macro averaging follow the same pattern as evidence identification.

### 6.2 Weighted Alignment

Each gold alignment pair (a, e) receives a weight based on the adjudicated relevance
of the evidence sentence e:
- **essential**: weight = 1.0
- **supplementary**: weight = 0.5

Weighted metrics:

- **Weighted precision** = Σ(weights of correct predicted pairs) / |predicted pairs|
  - A correct prediction of an essential alignment contributes 1.0
  - A correct prediction of a supplementary alignment contributes 0.5
  - An incorrect prediction contributes 0 to the numerator but 1 to the denominator

- **Weighted recall** = Σ(weights of correct predicted pairs) / Σ(weights of all gold pairs)

- **Weighted F1** = 2 × wP × wR / (wP + wR)

Micro: pool weighted TP, total predicted count, and total gold weight across cases.
Macro: compute weighted P/R/F1 per case, then average.

## 7. Inter-Annotator Agreement

The framework must report a chance-corrected agreement statistic for the
multi-annotator evidence labeling data. The data has these properties:

- **Multiple annotators**: Each sentence is labeled by 3 annotators.
- **Nominal scale**: Labels are unordered categories (essential, supplementary,
  not-relevant).
- **All categories meaningful**: The "not-relevant" label is an active annotation
  choice, not a missing value. The agreement statistic must use ALL annotator
  labels including "not-relevant".

Requirements for the chosen statistic:
1. It must be designed for multi-annotator settings (not pairwise averaging).
2. It must use a nominal distance function.
3. It must correct for chance agreement.
4. It must use ALL label categories. Filtering labels (e.g., excluding "not-relevant")
   before computing agreement invalidates the computation by removing the base-rate
   information needed for the chance correction term.

Evaluate the current implementation in `scorer/metrics.py` to determine whether it
satisfies these requirements and produces a correct value.

## 8. R Cross-Validation

An R script at `validate/check_alpha.R` must independently compute the
inter-annotator agreement statistic by reading the annotation data from the SQLite
database and implementing the same algorithm as the Python code. The R result must
match the Python result within 0.001.

The R script writes its numeric result to `output/alpha_validation.txt`.

The entry point includes the R-computed value in the final output JSON as
`r_validated_alpha` under the `inter_annotator_agreement` section.

## 9. Output Format

The output JSON at the specified path must contain:

```json
{
  "evidence_identification": {
    "strict": {
      "micro_precision": float,
      "micro_recall": float,
      "micro_f1": float,
      "macro_precision": float,
      "macro_recall": float,
      "macro_f1": float,
      "bootstrap_ci_micro_f1_lower": float,
      "bootstrap_ci_micro_f1_upper": float
    },
    "lenient": { "...same fields..." }
  },
  "evidence_alignment": {
    "standard": {
      "micro_precision": float,
      "micro_recall": float,
      "micro_f1": float,
      "macro_precision": float,
      "macro_recall": float,
      "macro_f1": float
    },
    "weighted": { "...same fields..." }
  },
  "inter_annotator_agreement": {
    "krippendorff_alpha": float,
    "r_validated_alpha": float
  },
  "diagnostics": {
    "threshold_sensitivity": {
      "1": {"total_strict_evidence": int, "total_lenient_evidence": int},
      "2": {"total_strict_evidence": int, "total_lenient_evidence": int},
      "3": {"total_strict_evidence": int, "total_lenient_evidence": int}
    },
    "scoring_consistency": {
      "lenient_gte_strict_micro_f1": bool,
      "lenient_gte_strict_macro_f1": bool
    }
  }
}
```

## 10. Pipeline Diagnostics

The output must include a diagnostics section evaluating pipeline behavior:

### 10.1 Threshold Sensitivity Analysis

Report the total number of strict and lenient evidence sentences (summed across all
cases) at adjudication thresholds 1, 2, and 3. This reveals how sensitive the gold
standard is to the threshold choice.

The evidence counts at each threshold must be computed by re-running the adjudication
protocol (Section 3) with the specified threshold and summing per-case evidence set
sizes.

### 10.2 Scoring Consistency Validation

Verify the mathematical invariant that lenient F1 >= strict F1 for both micro and
macro averages. This invariant holds because lenient scoring removes supplementary-only
predictions (reducing false positives) while preserving true positives.

Report boolean flags indicating whether each invariant holds.
