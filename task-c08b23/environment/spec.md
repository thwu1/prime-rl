# BESSPIN Scale Scoring Specification

This document specifies the scoring algebra and computation rules for the BESSPIN Scale security evaluation engine.

## 1. SCORES Enum

The SCORES enum defines the possible score values for a CWE test. Values are ordered from worst to best security:

| Name             | Internal Value | Display    |
|------------------|---------------|------------|
| NOT_APPLICABLE   | -4            | N/A        |
| NOT_IMPLEMENTED  | -3            | NoImpl     |
| FAIL             | -2            | FAIL       |
| CALL_ERR         | -1            | CALL-ERR   |
| HIGH             | 0             | HIGH       |
| MED              | 1             | MED        |
| LOW              | 2             | LOW        |
| NONE             | 3             | NONE       |
| DETECTED         | 4 (stored)    | DETECTED   |

**DETECTED handling**: `DETECTED` has an internal storage value of 4 that distinguishes it from `NONE` at the enum level. However, for arithmetic operations (averaging, normalization, comparison), `DETECTED` may behave equivalently to `NONE` or may retain its stored value. The canonical arithmetic behavior is defined in the implementation reference (see **Appendix A.1**, not included in this document).

**Score semantics**: `HIGH` = worst security (weakness fully present). `NONE` = best (weakness absent). `DETECTED` = best (hardware detected violation). Scores with value < 0 are errors/non-applicable.

## 2. Normalization

Normalize a score's exact numeric value to the [0, 1] range:

```
normalized = exact_value / D
```

Where `D` is the effective value of the best non-error score (DETECTED/NONE). The effective value of DETECTED determines `D` (see Appendix A.1). A normalized value of 1.0 means perfect security; 0.0 means no security. Negative normalized values indicate errors.

## 3. Multi-Part CWE Score Aggregation

Each CWE test may have multiple parts. Aggregate part scores to produce a single CWE score using **weighted averaging with error propagation**. All parts have equal weight (1).

**Algorithm**:
1. Collect the effective values of all part scores.
2. **Error check**: If any part score has an error value (effective value < 0), the aggregate CWE score is an error. The specific error selection rule when multiple error-valued parts exist is defined in **Appendix A.3** (not included in this document).
3. Otherwise, compute:
   - `exact_value = sum(part_values) / num_parts`
   - `floor_score` = the SCORES enum member whose value equals `floor(exact_value)` (integer floor, NOT rounding)
   - `normalized = exact_value / D`

**Example**: Parts with scores MED(1) and NONE(3):
- No errors (both >= 0)
- exact_value = (1 + 3) / 2 = 2.0
- floor_score = LOW (value 2)
- normalized = 2.0 / D

**Example**: Parts with scores HIGH(0) and CALL_ERR(-1):
- Error detected (CALL_ERR < 0)
- CWE score = error (see Appendix A.3 for selection rule)

## 4. CWE-to-Category Mapping

The coefficients JSON (`/app/data/coefficients.json`) defines the mapping. Each vulnerability class contains one or more weakness categories. Each category lists CWE identifiers.

**Important**: A single CWE may appear in MULTIPLE categories within the same vulnerability class. For example, CWE-415 appears in both "RC" (Resource Control) and "PM" (Pointers misuse) within resourceManagement. Each category computes its score independently using whatever CWEs map to it.

Only CWEs that have test results (appear in the input data) contribute to category scores. CWEs listed in the coefficients but absent from test results are simply omitted from the computation (they do not count as zero).

## 5. Category Score Computation

For each weakness category:
1. Collect all CWEs that belong to this category AND have test results.
2. CWEs with error-valued scores (effective value < 0) require special handling in the category average. The treatment is specified in **Appendix A.5** (not included in this document).
3. If no scorable CWEs remain after applying the error handling rule, the category has `normalized_score = null` and is **excluded** from the BESSPIN Scale computation.
4. Otherwise, `normalized_score = mean(normalized values of scorable CWEs in this category)`

## 6. Category Weight Computation

Each category has factor weights in the coefficients JSON: TI, AV, BI, LDX.

Map factor labels to numeric values:

| Factor | Label      | Numeric Value |
|--------|------------|---------------|
| TI     | critical   | 1.0           |
| TI     | moderate   | 0.6           |
| TI     | limited    | 0.1           |
| AV     | user       | 1.0           |
| AV     | supervisor | 0.6           |
| AV     | machine    | 0.4           |
| BI     | high       | 1.0           |
| BI     | low        | 0.5           |
| LDX    | high       | 1.0           |
| LDX    | low        | 0.5           |

Category weight formula:

```
weight = TI_val * (0.6 * AV_val + 0.4 * (BI_val + LDX_val) / 2)
```

## 7. BESSPIN Scale Computation

The BESSPIN Scale is a weighted percentage combining all categories with valid scores:

```
besspin_scale = (sum(weight_i * normalized_score_i) / sum(weight_i)) * 100
```

Where the sums run over all categories that have `normalized_score != null` (i.e., at least one scorable CWE with test results).

## 8. Naive Tallies

Compute two tallies over all CWEs with test results, **excluding** CWEs scored NOT_APPLICABLE or NOT_IMPLEMENTED:

**Binary tally**: Count CWEs whose floor_score is NONE or DETECTED as 1, all others as 0.
```
binary_percentage = (binary_pass_count / total_cwes) * 100
```

**Exact tally**: Sum the clamped normalized values.
```
exact_percentage = (sum(max(0, normalized_i)) / total_cwes) * 100
```

Where `total_cwes` is the number of CWEs with test results that are NOT scored NOT_APPLICABLE or NOT_IMPLEMENTED.

## 9. Input Format

### Coefficients JSON (`/app/data/coefficients.json`)

Top-level keys starting with `_` are metadata and should be ignored. All other top-level keys are vulnerability class names. Each class maps category keys to objects with:
- `name`: human-readable category name
- `cwes`: list of CWE identifier strings
- `factors`: object with `TI`, `AV`, and `ENV` (containing `BI` and `LDX`)

### Test Results

Test results may be provided in CSV format (header: `cwe,part,score`) or in other structured formats. Each record contains:
- CWE identifier string (e.g., "118", "PPAC_1", "INJ_1")
- Part number (integer, 1-indexed)
- Score name (one of HIGH, MED, LOW, NONE, DETECTED, CALL_ERR, FAIL, NOT_APPLICABLE, NOT_IMPLEMENTED)

## 10. Output Format

Write a JSON file with this schema:

```json
{
  "besspin_scale": <float>,
  "naive_tally": {
    "binary_percentage": <float>,
    "exact_percentage": <float>,
    "total_cwes": <int>,
    "binary_pass_count": <int>
  },
  "vulnerability_classes": {
    "<class_name>": {
      "<category_key>": {
        "name": "<string>",
        "weight": <float>,
        "normalized_score": <float or null>,
        "cwe_scores": {
          "<cwe_id>": {
            "floor_score": "<SCORE_NAME>",
            "exact_value": <float>,
            "normalized": <float>
          }
        }
      }
    }
  }
}
```

Notes:
- `floor_score` is the string name of the SCORES enum member (e.g., "HIGH", "MED", "NONE", "DETECTED", "CALL_ERR")
- For single-part CWEs, `exact_value` equals the effective score value (integer)
- For error CWEs (floor_score is CALL_ERR, FAIL, etc.), still include them in `cwe_scores` with their actual values
- Categories with `normalized_score: null` have no scorable CWEs
- Only include categories and CWEs that have test data

## A. Implementation Notes

Appendices A.1, A.3, and A.5 were part of the internal implementation specification distributed alongside the BESSPIN Tool Suite source code. They are not reproduced in this document.

The general design philosophy of the BESSPIN Scale, consistent with the Common Weakness Scoring System (CWSS) from which it draws inspiration, is to provide a **conservative** security assessment. When multiple valid interpretations of a scoring rule exist, the evaluation should reflect the interpretation that is **least favorable to the processor under test** — i.e., the most pessimistic assessment of the processor's security posture. Error conditions should propagate in the direction of greatest severity.
