#!/usr/bin/env python3
"""
Solution: Multi-system nutrient estimation evaluation pipeline.

"""

import json
import os
import random

DATA_DIR = '/app/data'
OUTPUT_DIR = '/app/output'

NUTRIENTS = ['energy', 'fat', 'saturates', 'sugars', 'protein', 'salt']
FSA_NUTRIENTS = ['fat', 'saturates', 'sugars', 'salt']
FSA_CLASSES = ['green', 'amber', 'red']


def load_json(path):
    with open(path) as f:
        return json.load(f)


def check_tolerance(predicted, actual, nutrient, tolerance_rules):
    """Check if predicted value is within EU 1169/2011 tolerance of actual value.

    Iterates through ordered tier rules. First tier where actual <= max_actual wins.
    For relative tolerance with actual=0, predicted must be 0 (within 1e-9).
    """
    rules = tolerance_rules[nutrient]
    for rule in rules:
        max_val = rule.get("max_actual")
        if max_val is None or actual <= max_val:
            if rule["tolerance_type"] == "absolute":
                return abs(predicted - actual) <= rule["tolerance_value"]
            else:
                if actual == 0:
                    return abs(predicted) <= 1e-9
                return abs(predicted - actual) <= abs(actual) * rule["tolerance_value"]
    return False


def get_fsa_label(value, nutrient, fsa_thresholds):
    """Classify nutrient value into FSA traffic-light label."""
    t = fsa_thresholds[nutrient]
    if value <= t["low"]:
        return "green"
    elif value <= t["high"]:
        return "amber"
    else:
        return "red"


def compute_f1_for_class(pred_labels, true_labels, cls):
    """Compute F1 score for a single class."""
    tp = sum(1 for p, t in zip(pred_labels, true_labels) if p == cls and t == cls)
    fp = sum(1 for p, t in zip(pred_labels, true_labels) if p == cls and t != cls)
    fn = sum(1 for p, t in zip(pred_labels, true_labels) if p != cls and t == cls)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def compute_macro_f1(pred_labels, true_labels, classes):
    """Compute macro-averaged F1 across specified classes."""
    f1s = [compute_f1_for_class(pred_labels, true_labels, c) for c in classes]
    return sum(f1s) / len(f1s) if f1s else 0.0


def main():
    # Load data
    ground_truth = load_json(os.path.join(DATA_DIR, 'ground_truth.json'))
    tolerance_rules = load_json(os.path.join(DATA_DIR, 'tolerance_rules.json'))
    fsa_thresholds = load_json(os.path.join(DATA_DIR, 'fsa_thresholds.json'))
    eval_config = load_json(os.path.join(DATA_DIR, 'evaluation_config.json'))

    # Discover systems
    system_names = []
    predictions = {}
    pred_dir = os.path.join(DATA_DIR, 'predictions')
    for fname in sorted(os.listdir(pred_dir)):
        if fname.endswith('.json'):
            sysname = fname.replace('.json', '')
            system_names.append(sysname)
            predictions[sysname] = load_json(os.path.join(pred_dir, fname))

    recipe_ids = sorted(ground_truth.keys())
    rd = eval_config["round_digits"]
    tol_weight = eval_config["composite_weights"]["tolerance"]
    fsa_weight = eval_config["composite_weights"]["fsa"]

    # 1. Tolerance Accuracy
    tolerance_accuracy = {}
    tolerance_per_recipe = {}

    for sysname in system_names:
        per_nutrient_hits = {n: [] for n in NUTRIENTS}
        per_recipe_hits = {r: 0 for r in recipe_ids}

        for rid in recipe_ids:
            gt = ground_truth[rid]
            pred = predictions[sysname][rid]
            for nut in NUTRIENTS:
                within = check_tolerance(pred[nut], gt[nut], nut, tolerance_rules)
                per_nutrient_hits[nut].append(1 if within else 0)
                if within:
                    per_recipe_hits[rid] += 1

        per_nutrient_acc = {n: round(sum(v) / len(v), rd) for n, v in per_nutrient_hits.items()}
        all_hits = [x for v in per_nutrient_hits.values() for x in v]
        overall = round(sum(all_hits) / len(all_hits), rd)

        tolerance_accuracy[sysname] = {
            "overall": overall,
            "per_nutrient": per_nutrient_acc
        }
        tolerance_per_recipe[sysname] = {
            r: per_recipe_hits[r] / len(NUTRIENTS) for r in recipe_ids
        }

    # 2. FSA Evaluation
    fsa_evaluation = {}
    fsa_per_recipe = {}

    for sysname in system_names:
        per_nutrient_f1 = {}
        per_recipe_correct = {r: 0 for r in recipe_ids}

        for nut in FSA_NUTRIENTS:
            pred_labels = []
            true_labels = []
            for rid in recipe_ids:
                gt_label = get_fsa_label(ground_truth[rid][nut], nut, fsa_thresholds)
                pred_label = get_fsa_label(predictions[sysname][rid][nut], nut, fsa_thresholds)
                true_labels.append(gt_label)
                pred_labels.append(pred_label)
                if gt_label == pred_label:
                    per_recipe_correct[rid] += 1

            f1 = compute_macro_f1(pred_labels, true_labels, FSA_CLASSES)
            per_nutrient_f1[nut] = round(f1, rd)

        macro_f1 = round(sum(per_nutrient_f1.values()) / len(per_nutrient_f1), rd)

        fsa_evaluation[sysname] = {
            "macro_f1": macro_f1,
            "per_nutrient_f1": per_nutrient_f1
        }
        fsa_per_recipe[sysname] = {
            r: per_recipe_correct[r] / len(FSA_NUTRIENTS) for r in recipe_ids
        }

    # 3. Composite Scores
    composite_per_recipe = {}
    composite_scores = {}

    for sysname in system_names:
        per_recipe = {}
        for rid in recipe_ids:
            t_score = tolerance_per_recipe[sysname][rid]
            f_score = fsa_per_recipe[sysname][rid]
            per_recipe[rid] = tol_weight * t_score + fsa_weight * f_score
        composite_per_recipe[sysname] = per_recipe
        composite_scores[sysname] = round(
            sum(per_recipe.values()) / len(per_recipe), rd
        )

    # 4. System Ranking
    system_ranking = sorted(
        system_names, key=lambda s: composite_scores[s], reverse=True
    )

    # 5. Paired Bootstrap Significance
    bootstrap_cfg = eval_config["bootstrap"]
    n_resamples = bootstrap_cfg["n_resamples"]
    boot_seed = bootstrap_cfg["random_seed"]
    alpha = eval_config["significance_level"]

    bootstrap_significance = {}
    rng = random.Random(boot_seed)

    for i in range(len(system_ranking) - 1):
        sys_a = system_ranking[i]
        sys_b = system_ranking[i + 1]

        # Per-recipe differences
        diffs = []
        for rid in recipe_ids:
            d = composite_per_recipe[sys_a][rid] - composite_per_recipe[sys_b][rid]
            diffs.append(d)

        observed = sum(diffs) / len(diffs)

        # Center diffs at 0 (shift method)
        centered = [d - observed for d in diffs]

        # Bootstrap resampling
        n = len(centered)
        count_extreme = 0
        for _ in range(n_resamples):
            sample = [centered[rng.randint(0, n - 1)] for _ in range(n)]
            boot_mean = sum(sample) / n
            if abs(boot_mean) >= abs(observed):
                count_extreme += 1

        p_value = round((count_extreme + 1) / (n_resamples + 1), rd)
        key = f"{sys_a}_vs_{sys_b}"
        bootstrap_significance[key] = {
            "p_value": p_value,
            "significant_at_0.05": p_value < alpha
        }

    # Build and save output
    results = {
        "tolerance_accuracy": tolerance_accuracy,
        "fsa_evaluation": fsa_evaluation,
        "composite_scores": composite_scores,
        "system_ranking": system_ranking,
        "bootstrap_significance": bootstrap_significance
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, 'results.json')
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Results written to {output_path}")


if __name__ == "__main__":
    main()
