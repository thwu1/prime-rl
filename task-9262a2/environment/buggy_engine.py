#!/usr/bin/env python3
"""Hierarchical rubric scoring engine for PaperBench-format evaluation rubrics."""

import argparse
import json
import sys
from pathlib import Path


def load_json(path):
    with open(path) as f:
        return json.load(f)


def get_leaves(node):
    """Collect all leaf nodes from a rubric tree."""
    if not node.get("sub_tasks"):
        return [node]
    leaves = []
    for child in node["sub_tasks"]:
        leaves.extend(get_leaves(child))
    return leaves


def compute_score(node, grades):
    """Compute the weighted replication score bottom-up."""
    if not node.get("sub_tasks"):
        return float(grades[node["id"]])
    total_weight = sum(c["weight"] for c in node["sub_tasks"])
    weighted_sum = sum(
        c["weight"] * compute_score(c, grades) for c in node["sub_tasks"]
    )
    return weighted_sum / total_weight


def compute_pruned_score(node, grades, depth_limit, current_depth=0):
    """Compute pruned score with depth-limited aggregation."""
    if not node.get("sub_tasks"):
        return float(grades[node["id"]])

    if current_depth > depth_limit:
        leaves = get_leaves(node)
        leaf_grades = [float(grades[leaf["id"]]) for leaf in leaves]
        return sum(leaf_grades) / len(leaf_grades)

    total_weight = sum(c["weight"] for c in node["sub_tasks"])
    weighted_sum = sum(
        c["weight"] * compute_pruned_score(c, grades, depth_limit, current_depth + 1)
        for c in node["sub_tasks"]
    )
    return weighted_sum / total_weight


def get_max_depth(node, current_depth=0):
    """Return the maximum depth of any node in the tree."""
    if not node.get("sub_tasks"):
        return current_depth
    return max(
        get_max_depth(c, current_depth + 1) for c in node["sub_tasks"]
    )


def compute_sensitivity(node, path_weight=1.0):
    """Compute effective weight for each leaf."""
    if not node.get("sub_tasks"):
        return {node["id"]: path_weight}

    total_weight = sum(c["weight"] for c in node["sub_tasks"])
    result = {}
    for child in node["sub_tasks"]:
        child_fraction = child["weight"] / total_weight
        child_sensitivities = compute_sensitivity(child, child_fraction)
        result.update(child_sensitivities)
    return result


def cmd_score(args):
    rubric = load_json(args.rubric)
    grades = load_json(args.grades)
    score = compute_score(rubric, grades)
    print(json.dumps({"replication_score": score}))


def cmd_prune_score(args):
    rubric = load_json(args.rubric)
    grades = load_json(args.grades)
    full_score = compute_score(rubric, grades)
    pruned_score = compute_pruned_score(rubric, grades, args.depth)
    absolute_error = abs(pruned_score - full_score)
    print(json.dumps({
        "pruned_score": pruned_score,
        "full_score": full_score,
        "absolute_error": absolute_error,
    }))


def cmd_optimal_depth(args):
    rubrics_dir = Path(args.rubrics_dir)
    grades_dir = Path(args.grades_dir)
    epsilon = args.epsilon

    pairs = []
    for rubric_file in sorted(rubrics_dir.glob("*.json")):
        grade_file = grades_dir / rubric_file.name
        if grade_file.exists():
            rubric = load_json(rubric_file)
            grades = load_json(grade_file)
            full_score = compute_score(rubric, grades)
            max_d = get_max_depth(rubric)
            pairs.append((rubric, grades, full_score, max_d))

    if not pairs:
        print(json.dumps({"optimal_depth": 0, "max_error": 0.0}))
        return

    overall_max_depth = max(md for _, _, _, md in pairs)

    for d in range(1, overall_max_depth + 1):
        max_error = min(
            abs(compute_pruned_score(r, g, d) - fs) for r, g, fs, _ in pairs
        )
        if max_error <= epsilon:
            print(json.dumps({"optimal_depth": d, "max_error": max_error}))
            return

    print(json.dumps({"optimal_depth": overall_max_depth, "max_error": 0.0}))


def cmd_judge_eval(args):
    rubric = load_json(args.rubric)
    gt = load_json(args.ground_truth)
    pred = load_json(args.predicted)

    leaves = get_leaves(rubric)

    categories = {}
    for leaf in leaves:
        cat = leaf.get("task_category", "Unknown")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(leaf["id"])

    per_category = {}
    for cat in sorted(categories.keys()):
        leaf_ids = categories[cat]
        tp = fp = fn = tn = 0
        for lid in leaf_ids:
            g = gt[lid]
            p = pred[lid]
            if g == 1 and p == 1:
                tp += 1
            elif g == 0 and p == 1:
                fp += 1
            elif g == 1 and p == 0:
                fn += 1
            else:
                tn += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (precision + recall) / 2 if (precision + recall) > 0 else 0.0

        per_category[cat] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }

    n = len(per_category)
    macro_p = sum(v["precision"] for v in per_category.values()) / n
    macro_r = sum(v["recall"] for v in per_category.values()) / n
    macro_f1 = sum(v["f1"] for v in per_category.values()) / n

    print(json.dumps({
        "per_category": per_category,
        "macro_average": {
            "precision": macro_p,
            "recall": macro_r,
            "f1": macro_f1,
        },
    }))


def cmd_sensitivity(args):
    rubric = load_json(args.rubric)
    sensitivities = compute_sensitivity(rubric)
    print(json.dumps({"sensitivities": sensitivities}))


def cmd_stratified_score(args):
    rubric = load_json(args.rubric)
    grades = load_json(args.grades)

    sensitivities = compute_sensitivity(rubric)
    leaves = get_leaves(rubric)

    categories = {}
    for leaf in leaves:
        cat = leaf.get("task_category", "Unknown")
        if cat not in categories:
            categories[cat] = {"contribution": 0.0, "coverage": 0.0}
        lid = leaf["id"]
        sens = sensitivities[lid]
        grade = float(grades[lid])
        categories[cat]["contribution"] += sens * grade
        categories[cat]["coverage"] += sens

    total_score = sum(d["contribution"] for d in categories.values())

    result_cats = {}
    for cat in sorted(categories.keys()):
        data = categories[cat]
        cond = data["contribution"] / total_score if total_score > 0 else 0.0
        result_cats[cat] = {
            "contribution": data["contribution"],
            "coverage": data["coverage"],
            "conditional_score": cond,
        }

    print(json.dumps({
        "categories": result_cats,
        "total_score": total_score,
    }))


def cmd_agreement(args):
    rubric = load_json(args.rubric)
    predictions_dir = Path(args.predictions_dir)

    leaves = get_leaves(rubric)
    leaf_ids = [leaf["id"] for leaf in leaves]

    pred_files = sorted(predictions_dir.glob("*.json"))
    predictions = [load_json(f) for f in pred_files]
    num_raters = len(predictions)
    num_subjects = len(leaf_ids)

    cat_map = {}
    for leaf in leaves:
        cat = leaf.get("task_category", "Unknown")
        if cat not in cat_map:
            cat_map[cat] = []
        cat_map[cat].append(leaf["id"])

    def fleiss_kappa(subject_ids, preds):
        n = len(subject_ids)
        N = len(preds)
        if n == 0 or N < 2:
            return 0.0

        total_0 = 0
        total_1 = 0
        p_bar_sum = 0.0

        for sid in subject_ids:
            n_1 = sum(1 for p in preds if p[sid] == 1)
            n_0 = N - n_1
            total_0 += n_0
            total_1 += n_1
            p_i = (n_0 * (n_0 - 1) + n_1 * (n_1 - 1)) / (N * (N - 1))
            p_bar_sum += p_i

        p_bar = p_bar_sum / n

        p_0 = total_0 / (n * N)
        p_1 = total_1 / (n * N)
        p_e = 2 * p_0 * p_1

        if abs(1.0 - p_e) < 1e-12:
            return 1.0 if abs(p_bar - 1.0) < 1e-12 else 0.0

        return (p_bar - p_e) / (1.0 - p_e)

    overall_kappa = fleiss_kappa(leaf_ids, predictions)

    per_category = {}
    for cat in sorted(cat_map.keys()):
        kappa = fleiss_kappa(cat_map[cat], predictions)
        per_category[cat] = {"kappa": kappa}

    print(json.dumps({
        "overall_kappa": overall_kappa,
        "per_category": per_category,
        "num_raters": num_raters,
        "num_subjects": num_subjects,
    }))


def cmd_score_bounds(args):
    raise NotImplementedError("score-bounds is not yet implemented")


def main():
    parser = argparse.ArgumentParser(
        description="Hierarchical rubric scoring engine"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_score = subparsers.add_parser("score",
                                    help="Compute weighted replication score")
    p_score.add_argument("--rubric", required=True)
    p_score.add_argument("--grades", required=True)

    p_prune = subparsers.add_parser("prune-score",
                                    help="Compute pruned replication score")
    p_prune.add_argument("--rubric", required=True)
    p_prune.add_argument("--grades", required=True)
    p_prune.add_argument("--depth", type=int, required=True)

    p_opt = subparsers.add_parser("optimal-depth",
                                  help="Find minimum pruning depth within tolerance")
    p_opt.add_argument("--rubrics-dir", required=True)
    p_opt.add_argument("--grades-dir", required=True)
    p_opt.add_argument("--epsilon", type=float, required=True)

    p_judge = subparsers.add_parser("judge-eval",
                                    help="Evaluate judge accuracy")
    p_judge.add_argument("--rubric", required=True)
    p_judge.add_argument("--ground-truth", required=True)
    p_judge.add_argument("--predicted", required=True)

    p_sens = subparsers.add_parser("sensitivity",
                                   help="Compute per-leaf effective weights")
    p_sens.add_argument("--rubric", required=True)
    p_sens.add_argument("--grades", required=True)

    p_strat = subparsers.add_parser("stratified-score",
                                    help="Decompose score by task category")
    p_strat.add_argument("--rubric", required=True)
    p_strat.add_argument("--grades", required=True)

    p_agree = subparsers.add_parser("agreement",
                                    help="Compute inter-judge agreement")
    p_agree.add_argument("--rubric", required=True)
    p_agree.add_argument("--predictions-dir", required=True)

    p_bounds = subparsers.add_parser("score-bounds",
                                     help="Compute score bounds under grade uncertainty")
    p_bounds.add_argument("--rubric", required=True)
    p_bounds.add_argument("--grades", required=True)
    p_bounds.add_argument("--uncertain", required=True,
                          help="Comma-separated list of uncertain leaf IDs")

    args = parser.parse_args()

    commands = {
        "score": cmd_score,
        "prune-score": cmd_prune_score,
        "optimal-depth": cmd_optimal_depth,
        "judge-eval": cmd_judge_eval,
        "sensitivity": cmd_sensitivity,
        "stratified-score": cmd_stratified_score,
        "agreement": cmd_agreement,
        "score-bounds": cmd_score_bounds,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
