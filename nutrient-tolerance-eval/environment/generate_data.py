#!/usr/bin/env python3
"""Generate deterministic evaluation data for the nutrient compliance pipeline task."""

import json
import os
import random

random.seed(42)

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

tolerance_rules = {
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

fsa_thresholds = {
    "fat": {"low": 3.0, "high": 17.5},
    "saturates": {"low": 1.5, "high": 5.0},
    "sugars": {"low": 5.0, "high": 22.5},
    "salt": {"low": 0.3, "high": 1.5}
}

eval_config = {
    "composite_weights": {"tolerance": 0.6, "fsa": 0.4},
    "bootstrap": {
        "n_resamples": 10000,
        "random_seed": 42
    },
    "significance_level": 0.05,
    "round_digits": 4
}

os.makedirs('/app/data/predictions', exist_ok=True)
os.makedirs('/app/output', exist_ok=True)

with open('/app/data/ground_truth.json', 'w') as f:
    json.dump(GROUND_TRUTH, f, indent=2)

for sysname, preds in systems.items():
    with open('/app/data/predictions/{}.json'.format(sysname), 'w') as f:
        json.dump(preds, f, indent=2)

with open('/app/data/tolerance_rules.json', 'w') as f:
    json.dump(tolerance_rules, f, indent=2)

with open('/app/data/fsa_thresholds.json', 'w') as f:
    json.dump(fsa_thresholds, f, indent=2)

with open('/app/data/evaluation_config.json', 'w') as f:
    json.dump(eval_config, f, indent=2)

print("Data generation complete.")
