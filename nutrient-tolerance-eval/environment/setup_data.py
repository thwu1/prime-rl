#!/usr/bin/env python3
"""Generate evaluation data, reference documentation, validation cases, and Makefile.

Runs at Docker build time to populate /app/data/, /app/docs/, and /app/Makefile.
"""

import json
import math
import os
import random

random.seed(42)

# ============================================================
# Ground truth nutrient values (per 100 g)
# ============================================================
GROUND_TRUTH = {
    "R01": {"energy": 34.0, "fat": 0.4, "saturates": 0.1, "sugars": 1.7, "protein": 2.8, "salt": 0.04},
    "R02": {"energy": 210.0, "fat": 9.5, "saturates": 4.2, "sugars": 1.2, "protein": 8.5, "salt": 0.85},
    "R03": {"energy": 180.0, "fat": 14.0, "saturates": 2.5, "sugars": 2.3, "protein": 6.0, "salt": 1.1},
    "R04": {"energy": 380.0, "fat": 18.5, "saturates": 8.0, "sugars": 35.0, "protein": 5.5, "salt": 0.55},
    "R05": {"energy": 208.0, "fat": 13.0, "saturates": 3.1, "sugars": 0.0, "protein": 20.4, "salt": 0.38},
    "R06": {"energy": 42.0, "fat": 0.9, "saturates": 0.2, "sugars": 3.2, "protein": 1.5, "salt": 0.65},
    "R07": {"energy": 260.0, "fat": 15.0, "saturates": 3.0, "sugars": 0.5, "protein": 24.0, "salt": 1.6},
    "R08": {"energy": 85.0, "fat": 0.5, "saturates": 0.1, "sugars": 15.0, "protein": 1.8, "salt": 0.02},
    "R09": {"energy": 30.0, "fat": 0.8, "saturates": 0.2, "sugars": 1.5, "protein": 2.0, "salt": 2.2},
    "R10": {"energy": 607.0, "fat": 54.0, "saturates": 5.0, "sugars": 4.0, "protein": 20.0, "salt": 0.01},
    "R11": {"energy": 112.0, "fat": 0.1, "saturates": 0.0, "sugars": 23.0, "protein": 1.2, "salt": 2.8},
    "R12": {"energy": 50.0, "fat": 0.2, "saturates": 0.0, "sugars": 11.0, "protein": 0.6, "salt": 0.01},
    "R13": {"energy": 406.0, "fat": 21.0, "saturates": 12.0, "sugars": 6.0, "protein": 8.2, "salt": 1.2},
    "R14": {"energy": 115.0, "fat": 4.0, "saturates": 0.5, "sugars": 2.8, "protein": 7.5, "salt": 1.4},
    "R15": {"energy": 95.0, "fat": 1.0, "saturates": 0.5, "sugars": 8.0, "protein": 18.0, "salt": 0.3},
    "R16": {"energy": 266.0, "fat": 10.4, "saturates": 4.5, "sugars": 3.6, "protein": 11.4, "salt": 1.3},
    "R17": {"energy": 97.0, "fat": 5.0, "saturates": 3.3, "sugars": 3.9, "protein": 9.0, "salt": 0.07},
    "R18": {"energy": 130.0, "fat": 3.5, "saturates": 2.0, "sugars": 14.0, "protein": 3.2, "salt": 0.15},
    "R19": {"energy": 160.0, "fat": 14.7, "saturates": 2.1, "sugars": 0.7, "protein": 2.0, "salt": 0.3},
    "R20": {"energy": 227.0, "fat": 8.0, "saturates": 2.5, "sugars": 12.0, "protein": 6.3, "salt": 1.15},
}

NUTRIENTS = ['energy', 'fat', 'saturates', 'sugars', 'protein', 'salt']
FSA_NUTRIENTS = ['fat', 'saturates', 'sugars', 'salt']

TOLERANCE_RULES = {
    "energy": [
        {"max_actual": 80, "tolerance_type": "absolute", "tolerance_value": 8},
        {"max_actual": None, "tolerance_type": "relative", "tolerance_value": 0.10}
    ],
    "fat": [
        {"max_actual": 10, "tolerance_type": "absolute", "tolerance_value": 1.5},
        {"max_actual": 40, "tolerance_type": "relative", "tolerance_value": 0.20},
        {"max_actual": None, "tolerance_type": "absolute", "tolerance_value": 8}
    ],
    "saturates": [
        {"max_actual": 4, "tolerance_type": "absolute", "tolerance_value": 0.8},
        {"max_actual": None, "tolerance_type": "relative", "tolerance_value": 0.20}
    ],
    "sugars": [
        {"max_actual": 10, "tolerance_type": "absolute", "tolerance_value": 1.5},
        {"max_actual": 40, "tolerance_type": "relative", "tolerance_value": 0.20},
        {"max_actual": None, "tolerance_type": "absolute", "tolerance_value": 8}
    ],
    "protein": [
        {"max_actual": 10, "tolerance_type": "absolute", "tolerance_value": 2},
        {"max_actual": 40, "tolerance_type": "relative", "tolerance_value": 0.20},
        {"max_actual": None, "tolerance_type": "absolute", "tolerance_value": 8}
    ],
    "salt": [
        {"max_actual": 1.25, "tolerance_type": "absolute", "tolerance_value": 0.375},
        {"max_actual": None, "tolerance_type": "relative", "tolerance_value": 0.30}
    ]
}

FSA_THRESHOLDS = {
    "fat": {"low": 3.0, "high": 17.5},
    "saturates": {"low": 1.5, "high": 5.0},
    "sugars": {"low": 5.0, "high": 22.5},
    "salt": {"low": 0.3, "high": 1.5}
}

EVAL_CONFIG = {
    "composite_weights": {"tolerance": 0.6, "fsa": 0.4},
    "bootstrap": {"n_resamples": 10000, "random_seed": 42},
    "significance_level": 0.05,
    "round_digits": 4
}


# ============================================================
# Prediction generation
# ============================================================
def generate_predictions(gt, noise_scale, salt_bias=0.0):
    preds = {}
    for rid in sorted(gt.keys()):
        vals = gt[rid]
        pred = {}
        for nut in NUTRIENTS:
            actual = vals[nut]
            noise = random.gauss(0, noise_scale) * max(actual, 1.0)
            if nut == 'salt':
                noise += salt_bias
            pred[nut] = round(max(0.0, actual + noise), 2)
        preds[rid] = pred
    return preds


systems = {
    'sys_A': generate_predictions(GROUND_TRUTH, 0.06),
    'sys_B': generate_predictions(GROUND_TRUTH, 0.15),
    'sys_C': generate_predictions(GROUND_TRUTH, 0.22, salt_bias=0.5),
    'sys_D': generate_predictions(GROUND_TRUTH, 0.40),
}


# ============================================================
# Reference implementations (correct) for validation values
# ============================================================
def ref_check_tolerance(predicted, actual, nutrient, rules):
    for rule in rules[nutrient]:
        max_val = rule.get("max_actual")
        if max_val is None or actual <= max_val:
            if rule["tolerance_type"] == "absolute":
                return abs(predicted - actual) <= rule["tolerance_value"]
            else:
                if actual == 0:
                    return abs(predicted) <= 1e-9
                return abs(predicted - actual) <= abs(actual) * rule["tolerance_value"]
    return False


def ref_tolerance_bound(actual, nutrient, rules):
    """Compute the tolerance bound for a given actual value and nutrient."""
    for rule in rules[nutrient]:
        max_val = rule.get("max_actual")
        if max_val is None or actual <= max_val:
            if rule["tolerance_type"] == "absolute":
                return rule["tolerance_value"]
            else:
                if actual == 0:
                    return 1e-9
                return abs(actual) * rule["tolerance_value"]
    return 0.0


def ref_fsa_label(value, nutrient, thresholds):
    t = thresholds[nutrient]
    if value <= t["low"]:
        return "green"
    elif value <= t["high"]:
        return "amber"
    else:
        return "red"


def ref_f1_class(preds, trues, cls):
    tp = sum(1 for p, t in zip(preds, trues) if p == cls and t == cls)
    fp = sum(1 for p, t in zip(preds, trues) if p == cls and t != cls)
    fn = sum(1 for p, t in zip(preds, trues) if p != cls and t == cls)
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    if prec + rec == 0:
        return 0.0
    return 2 * prec * rec / (prec + rec)


# ============================================================
# Compute validation reference values
# ============================================================
recipe_ids = sorted(GROUND_TRUTH.keys())
system_names = sorted(systems.keys())
rd = EVAL_CONFIG["round_digits"]
tol_w = EVAL_CONFIG["composite_weights"]["tolerance"]
fsa_w = EVAL_CONFIG["composite_weights"]["fsa"]

# Tolerance accuracy
ref_tol_accuracy = {}
ref_tol_per_recipe = {}
for sysname in system_names:
    per_nut_hits = {n: [] for n in NUTRIENTS}
    per_recipe_hits = {r: 0 for r in recipe_ids}
    for rid in recipe_ids:
        g = GROUND_TRUTH[rid]
        p = systems[sysname][rid]
        for nut in NUTRIENTS:
            within = ref_check_tolerance(p[nut], g[nut], nut, TOLERANCE_RULES)
            per_nut_hits[nut].append(1 if within else 0)
            if within:
                per_recipe_hits[rid] += 1
    per_nut_acc = {n: round(sum(v) / len(v), rd) for n, v in per_nut_hits.items()}
    all_hits = [x for v in per_nut_hits.values() for x in v]
    overall = round(sum(all_hits) / len(all_hits), rd)
    ref_tol_accuracy[sysname] = {"overall": overall, "per_nutrient": per_nut_acc}
    ref_tol_per_recipe[sysname] = {r: per_recipe_hits[r] / len(NUTRIENTS) for r in recipe_ids}

# FSA evaluation
ref_fsa_per_recipe = {}
for sysname in system_names:
    per_recipe_correct = {r: 0 for r in recipe_ids}
    for nut in FSA_NUTRIENTS:
        for rid in recipe_ids:
            gt_label = ref_fsa_label(GROUND_TRUTH[rid][nut], nut, FSA_THRESHOLDS)
            pred_label = ref_fsa_label(systems[sysname][rid][nut], nut, FSA_THRESHOLDS)
            if gt_label == pred_label:
                per_recipe_correct[rid] += 1
    ref_fsa_per_recipe[sysname] = {r: per_recipe_correct[r] / len(FSA_NUTRIENTS) for r in recipe_ids}

# Composite scores
ref_composites = {}
ref_comp_per_recipe = {}
for sysname in system_names:
    per_recipe = {}
    for rid in recipe_ids:
        t_score = ref_tol_per_recipe[sysname][rid]
        f_score = ref_fsa_per_recipe[sysname][rid]
        per_recipe[rid] = tol_w * t_score + fsa_w * f_score
    ref_comp_per_recipe[sysname] = per_recipe
    ref_composites[sysname] = round(sum(per_recipe.values()) / len(per_recipe), rd)

ref_ranking = sorted(system_names, key=lambda s: ref_composites[s], reverse=True)

# Error analysis
ref_error_analysis = {}
for sysname in system_names:
    per_nut = {}
    for nut in NUTRIENTS:
        errors = []
        abs_errors = []
        sq_errors = []
        margins = []
        for rid in recipe_ids:
            predicted = systems[sysname][rid][nut]
            actual = GROUND_TRUTH[rid][nut]
            err = predicted - actual
            abs_err = abs(err)
            errors.append(err)
            abs_errors.append(abs_err)
            sq_errors.append(err ** 2)
            bound = ref_tolerance_bound(actual, nut, TOLERANCE_RULES)
            margin = (bound - abs_err) / bound if bound > 0 else 0.0
            margins.append(margin)
        bias = round(sum(errors) / len(errors), rd)
        mae = round(sum(abs_errors) / len(abs_errors), rd)
        rmse = round(math.sqrt(sum(sq_errors) / len(sq_errors)), rd)
        tol_margin = round(sum(margins) / len(margins), rd)
        per_nut[nut] = {"bias": bias, "mae": mae, "rmse": rmse, "tolerance_margin": tol_margin}
    overall_mae = round(sum(per_nut[n]["mae"] for n in NUTRIENTS) / len(NUTRIENTS), rd)
    overall_rmse = round(sum(per_nut[n]["rmse"] for n in NUTRIENTS) / len(NUTRIENTS), rd)
    mean_tol_margin = round(sum(per_nut[n]["tolerance_margin"] for n in NUTRIENTS) / len(NUTRIENTS), rd)
    ref_error_analysis[sysname] = {
        "per_nutrient": per_nut,
        "overall_mae": overall_mae,
        "overall_rmse": overall_rmse,
        "mean_tolerance_margin": mean_tol_margin
    }


# ============================================================
# Write data files
# ============================================================
os.makedirs('/app/data/predictions', exist_ok=True)
os.makedirs('/app/output', exist_ok=True)
os.makedirs('/app/docs', exist_ok=True)

with open('/app/data/ground_truth.json', 'w') as f:
    json.dump(GROUND_TRUTH, f, indent=2)

for sysname, preds in systems.items():
    with open(f'/app/data/predictions/{sysname}.json', 'w') as f:
        json.dump(preds, f, indent=2)

with open('/app/data/tolerance_rules.json', 'w') as f:
    json.dump(TOLERANCE_RULES, f, indent=2)

with open('/app/data/fsa_thresholds.json', 'w') as f:
    json.dump(FSA_THRESHOLDS, f, indent=2)

with open('/app/data/evaluation_config.json', 'w') as f:
    json.dump(EVAL_CONFIG, f, indent=2)


# ============================================================
# Generate Makefile with guaranteed tab characters
# ============================================================
# NOTE: We generate the Makefile from Python to ensure recipe lines
# use real tab characters, which is mandatory for GNU Make.
T = '\t'
makefile_content = (
    '.PHONY: evaluate clean\n'
    '\n'
    'DB = /app/pipeline.db\n'
    '\n'
    'evaluate: /app/output/results.json\n'
    '\n'
    '$(DB): /app/data/ground_truth.json /app/data/tolerance_rules.json'
    ' /app/data/fsa_thresholds.json /app/config/pipeline_config.toml'
    ' /app/src/load_data.py\n'
    f'{T}python3 /app/src/load_data.py\n'
    '\n'
    '/app/.tolerance_done: $(DB) /app/src/tolerance_check.py\n'
    f'{T}python3 /app/src/tolerance_check.py && touch $@\n'
    '\n'
    '/app/.fsa_done: $(DB) /app/src/fsa_labeler.py\n'
    f'{T}python3 /app/src/fsa_labeler.py && touch $@\n'
    '\n'
    '/app/.error_analysis_done: $(DB) /app/src/error_analysis.py\n'
    f'{T}python3 /app/src/error_analysis.py && touch $@\n'
    '\n'
    '/app/.scoring_done: /app/.tolerance_done /app/.fsa_done /app/src/scoring.py\n'
    f'{T}python3 /app/src/scoring.py && touch $@\n'
    '\n'
    '/app/.significance_done: /app/.scoring_done /app/src/significance.py\n'
    f'{T}python3 /app/src/significance.py && touch $@\n'
    '\n'
    '/app/output/results.json: /app/.significance_done /app/src/report.py\n'
    f'{T}python3 /app/src/report.py\n'
    '\n'
    'clean:\n'
    f'{T}rm -f $(DB) /app/output/results.json'
    ' /app/.tolerance_done /app/.fsa_done /app/.error_analysis_done'
    ' /app/.scoring_done /app/.significance_done\n'
)

with open('/app/Makefile', 'w') as f:
    f.write(makefile_content)


# ============================================================
# Write documentation
# ============================================================
with open('/app/docs/eu_regulation_tolerances.md', 'w') as f:
    f.write("""\
# EU Regulation 1169/2011 — Nutrient Declaration Tolerances

## Overview

Under EU Regulation 1169/2011 (Annex I, Section B), nutrient values declared
on food labels must fall within specified tolerances of the actual measured
values. These tolerances account for natural variation in food composition
and measurement uncertainty.

## Tolerance Methodology

For each nutrient, tolerance tiers are defined based on the
**actual (declared) value**:

1. Tiers are ordered by ascending `max_actual` thresholds.
2. The **first tier** where `actual_value <= max_actual` (or the tier is
   unbounded, i.e. `max_actual` is null) determines the applicable tolerance.
3. Tolerance types:
   - **Absolute**: `|predicted - actual| <= tolerance_value`
   - **Relative**: `|predicted - actual| <= actual * tolerance_value`

## Critical Detail: Reference Value for Relative Tolerance

The reference value for relative tolerance computation is always the
**actual (ground truth / declared) value**, not the predicted (measured) value.
This ensures the tolerance band is anchored to the known quantity.

## Special Cases

- When `actual = 0` and the tolerance type is relative, the predicted value
  must also be 0 (within measurement precision, i.e. `|predicted| <= 1e-9`).

## Tolerance Rules

See `/app/data/tolerance_rules.json` for the per-nutrient tier definitions.
Each entry contains:
- `max_actual`: upper bound for the tier (null = unbounded catch-all)
- `tolerance_type`: `"absolute"` or `"relative"`
- `tolerance_value`: the tolerance amount (absolute) or fraction (relative)
""")

with open('/app/docs/fsa_traffic_light_guide.md', 'w') as f:
    f.write("""\
# UK FSA Front-of-Pack Traffic-Light Classification

## Overview

The UK Food Standards Agency (FSA) traffic-light system classifies nutrient
levels per 100 g of food into three categories:

- **Green** (low): the nutrient level is low
- **Amber** (medium): the nutrient level is medium
- **Red** (high): the nutrient level is high

## Classification Rules

For each nutrient, two thresholds are defined: `low` and `high`.

| Condition                                      | Label     |
|------------------------------------------------|-----------|
| value **<= low**                               | **green** |
| value **> low** AND value **<= high**          | **amber** |
| value **> high**                               | **red**   |

**Important**: boundary values are inclusive on the lower side. A value
*exactly equal* to the low threshold is classified as **green**, not amber.
Similarly, a value exactly equal to the high threshold is **amber**, not red.

## Applicable Nutrients

fat, saturates (saturated fat), sugars, salt

## Thresholds

See `/app/data/fsa_thresholds.json` for threshold values.

## Evaluation Metric

Macro-averaged F1 score across all three classes (green, amber, red) is
computed per nutrient. The system's overall FSA score is the mean of the
per-nutrient macro-F1 values.
""")

with open('/app/docs/error_analysis_spec.md', 'w') as f:
    f.write("""\
# Error Analysis Module Specification

## Purpose

Quantifies prediction quality beyond binary tolerance compliance by computing
continuous error statistics and tolerance margin analysis for each prediction
system.

## Input

Reads from the pipeline SQLite database:
- `predictions` table: system predictions
- `recipes` table: ground truth values
- `tolerance_rules` table: tolerance tier definitions
- `config` table: rounding configuration

## Per-Nutrient Metrics

For each system and nutrient, compute across all recipes:

### Signed Mean Error (Bias)
    bias = (1/N) * sum(predicted_i - actual_i)
Indicates systematic over-prediction (positive) or under-prediction (negative).

### Mean Absolute Error (MAE)
    mae = (1/N) * sum(|predicted_i - actual_i|)
Average magnitude of prediction errors, regardless of direction.

### Root Mean Squared Error (RMSE)
    rmse = sqrt((1/N) * sum((predicted_i - actual_i)^2))
Penalizes large errors more heavily than MAE.

### Tolerance Margin

For each recipe, compute the applicable tolerance bound from the tolerance
rules, then measure how much margin remains relative to that bound:

1. **Determine the tolerance bound** for the actual value and nutrient:
   - Look through the tolerance tiers in order
   - The first tier where `actual <= max_actual` (or `max_actual` is null)
     determines the applicable tolerance
   - If `tolerance_type` is `"absolute"`: `bound = tolerance_value`
   - If `tolerance_type` is `"relative"`: `bound = actual * tolerance_value`
   - Special case: if `actual == 0` and type is `"relative"`:
     `bound = 1e-9`

2. **Compute the margin**:
       margin_i = (bound - |predicted_i - actual_i|) / bound

   - Positive margin: prediction is within tolerance with headroom
   - Zero: prediction is exactly at the tolerance boundary
   - Negative: prediction exceeds tolerance

3. **Average** across all recipes for the nutrient:
       tolerance_margin = (1/N) * sum(margin_i)

## Summary Metrics

For each system, compute overall summary values:
- `overall_mae` = mean of per-nutrient MAE values
- `overall_rmse` = mean of per-nutrient RMSE values
- `mean_tolerance_margin` = mean of per-nutrient tolerance_margin values

## Output Tables

### error_analysis_results
Columns: (system_name TEXT, nutrient TEXT, bias REAL, mae REAL, rmse REAL,
           tolerance_margin REAL)
Primary key: (system_name, nutrient)

### error_analysis_summary
Columns: (system_name TEXT, overall_mae REAL, overall_rmse REAL,
           mean_tolerance_margin REAL)
Primary key: (system_name)

## Rounding

Round all stored values to `round_digits` decimal places (read from
the `config` table, key `'round_digits'`).

## Integration

This module should populate the above tables so that the report generator
can include error analysis results in the final output JSON.
""")

# Validation cases with computed reference values
sys_a_tol = ref_tol_accuracy['sys_A']
sys_a_err = ref_error_analysis['sys_A']
with open('/app/docs/validation_cases.md', 'w') as f:
    f.write(f"""\
# Validation Cases

Independently verified correct results for pipeline output validation.

## FSA Traffic-Light Labels (Ground Truth)

| Recipe | Nutrient   | Value | Expected Label |
|--------|-----------|-------|----------------|
| R15    | salt      | 0.30  | green          |
| R19    | salt      | 0.30  | green          |
| R10    | saturates | 5.00  | amber          |
| R04    | fat       | 18.50 | red            |
| R01    | fat       | 0.40  | green          |

## Tolerance Band Verification

Recipe R03, fat (actual = 14.0 g/100g):
- Tier 2 applies (actual <= 40, relative +/-20%)
- Tolerance = 14.0 x 0.20 = 2.8 (computed from the **actual** value)
- Compliant prediction range: [11.2, 16.8]

Recipe R16, fat (actual = 10.4 g/100g):
- Tier 2 applies (actual <= 40, relative +/-20%)
- Tolerance = 10.4 x 0.20 = 2.08 (computed from the **actual** value)

## Per-Nutrient Tolerance Accuracy (sys_A)

| Nutrient   | Accuracy |
|-----------|----------|
| energy    | {sys_a_tol['per_nutrient']['energy']} |
| fat       | {sys_a_tol['per_nutrient']['fat']} |
| saturates | {sys_a_tol['per_nutrient']['saturates']} |
| sugars    | {sys_a_tol['per_nutrient']['sugars']} |
| protein   | {sys_a_tol['per_nutrient']['protein']} |
| salt      | {sys_a_tol['per_nutrient']['salt']} |

These values differ across nutrients (they must NOT all be identical).

## Error Analysis Verification (sys_A)

| Nutrient   | Bias    | MAE    | RMSE   | Tolerance Margin |
|-----------|---------|--------|--------|-----------------|
| energy    | {sys_a_err['per_nutrient']['energy']['bias']} | {sys_a_err['per_nutrient']['energy']['mae']} | {sys_a_err['per_nutrient']['energy']['rmse']} | {sys_a_err['per_nutrient']['energy']['tolerance_margin']} |
| fat       | {sys_a_err['per_nutrient']['fat']['bias']} | {sys_a_err['per_nutrient']['fat']['mae']} | {sys_a_err['per_nutrient']['fat']['rmse']} | {sys_a_err['per_nutrient']['fat']['tolerance_margin']} |
| salt      | {sys_a_err['per_nutrient']['salt']['bias']} | {sys_a_err['per_nutrient']['salt']['mae']} | {sys_a_err['per_nutrient']['salt']['rmse']} | {sys_a_err['per_nutrient']['salt']['tolerance_margin']} |

sys_A overall MAE: {sys_a_err['overall_mae']}
sys_A overall RMSE: {sys_a_err['overall_rmse']}
sys_A mean tolerance margin: {sys_a_err['mean_tolerance_margin']}

## Composite Scores

With tolerance_weight = 0.6 and fsa_weight = 0.4:

| System | Composite Score |
|--------|----------------|
| {ref_ranking[0]} | {ref_composites[ref_ranking[0]]} |
| {ref_ranking[1]} | {ref_composites[ref_ranking[1]]} |
| {ref_ranking[2]} | {ref_composites[ref_ranking[2]]} |
| {ref_ranking[3]} | {ref_composites[ref_ranking[3]]} |

Expected ranking: {', '.join(ref_ranking)}

## Statistical Significance

The difference between the top-ranked and second-ranked systems should be
statistically significant (p < 0.05).
""")

print("Data and documentation generated successfully.")
