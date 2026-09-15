#!/usr/bin/env python3
"""
Rubric Analysis Engine — reference implementation.

Analyzes hierarchical evaluation rubrics in PaperBench format.
"""

import argparse
import json
import sys


def load_json(path):
    with open(path) as f:
        return json.load(f)


def get_leaves(node):
    """Return all leaf nodes (those with empty sub_tasks)."""
    if not node.get("sub_tasks"):
        return [node]
    leaves = []
    for child in node["sub_tasks"]:
        leaves.extend(get_leaves(child))
    return leaves


def compute_score(node, grading):
    """Compute the weighted hierarchical score from leaf grades."""
    if not node.get("sub_tasks"):
        return float(grading.get(node["id"], 0))
    total_weight = sum(c["weight"] for c in node["sub_tasks"])
    weighted_sum = sum(
        c["weight"] * compute_score(c, grading) for c in node["sub_tasks"]
    )
    return weighted_sum / total_weight


def compute_effective_weights(node, parent_effective=1.0):
    """
    Compute the effective weight of each leaf node.

    The effective weight is the product of normalized weight ratios along the
    root-to-leaf path.  Flipping a leaf from 0 to 1 increases the root score
    by exactly its effective weight.
    """
    if not node.get("sub_tasks"):
        return {node["id"]: parent_effective}
    total_weight = sum(c["weight"] for c in node["sub_tasks"])
    result = {}
    for child in node["sub_tasks"]:
        child_effective = parent_effective * child["weight"] / total_weight
        result.update(compute_effective_weights(child, child_effective))
    return result


# ---- subcommands -----------------------------------------------------------

def cmd_score(args):
    rubric = load_json(args.rubric)
    grading = load_json(args.grading)
    score = compute_score(rubric, grading)
    print(json.dumps({"root_score": round(score, 6)}))


def cmd_sensitivity(args):
    rubric = load_json(args.rubric)
    ew = compute_effective_weights(rubric)
    sorted_items = sorted(ew.items(), key=lambda x: (-round(x[1], 9), x[0]))
    result = {k: round(v, 6) for k, v in sorted_items}
    print(json.dumps(result))


def cmd_stratify(args):
    rubric = load_json(args.rubric)
    grading = load_json(args.grading)
    ew = compute_effective_weights(rubric)
    leaves = get_leaves(rubric)

    categories: dict[str, dict[str, float]] = {}
    for leaf in leaves:
        cat = leaf.get("task_category", "Unknown")
        if cat not in categories:
            categories[cat] = {"weighted_score": 0.0, "total_weight": 0.0}
        score = float(grading.get(leaf["id"], 0))
        weight = ew[leaf["id"]]
        categories[cat]["weighted_score"] += weight * score
        categories[cat]["total_weight"] += weight

    result = {}
    for cat in sorted(categories.keys()):
        tw = categories[cat]["total_weight"]
        if tw > 0:
            result[cat] = round(categories[cat]["weighted_score"] / tw, 6)
        else:
            result[cat] = 0.0
    print(json.dumps(result))


def cmd_optimal_k(args):
    rubric = load_json(args.rubric)
    grading = load_json(args.grading)
    k = args.k
    ew = compute_effective_weights(rubric)
    current_score = compute_score(rubric, grading)

    unsatisfied = [
        (lid, w) for lid, w in ew.items() if grading.get(lid, 0) == 0
    ]
    unsatisfied.sort(key=lambda x: (-round(x[1], 9), x[0]))

    selected = [lid for lid, _ in unsatisfied[:k]]
    score_increase = sum(w for _, w in unsatisfied[:k])
    new_score = current_score + score_increase

    print(json.dumps({"leaves": selected, "new_score": round(new_score, 6)}))


def cmd_agreement(args):
    g1 = load_json(args.grading1)
    g2 = load_json(args.grading2)

    all_keys = sorted(set(g1.keys()) | set(g2.keys()))
    tp = fp = fn = tn = 0
    for key in all_keys:
        pred = g1.get(key, 0)
        ref = g2.get(key, 0)
        if pred == 1 and ref == 1:
            tp += 1
        elif pred == 1 and ref == 0:
            fp += 1
        elif pred == 0 and ref == 1:
            fn += 1
        else:
            tn += 1

    n = tp + fp + fn + tn
    accuracy = (tp + tn) / n if n > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    p_o = accuracy
    p_pred_1 = (tp + fp) / n if n > 0 else 0.0
    p_ref_1 = (tp + fn) / n if n > 0 else 0.0
    p_e = p_pred_1 * p_ref_1 + (1 - p_pred_1) * (1 - p_ref_1)
    kappa = (p_o - p_e) / (1 - p_e) if (1 - p_e) != 0 else 1.0

    print(
        json.dumps(
            {
                "cohens_kappa": round(kappa, 6),
                "accuracy": round(accuracy, 6),
                "precision": round(precision, 6),
                "recall": round(recall, 6),
                "f1": round(f1, 6),
            }
        )
    )


# ---- CLI -------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Rubric Analysis Engine")
    subparsers = parser.add_subparsers(dest="command")

    p_score = subparsers.add_parser("score")
    p_score.add_argument("--rubric", required=True)
    p_score.add_argument("--grading", required=True)

    p_sens = subparsers.add_parser("sensitivity")
    p_sens.add_argument("--rubric", required=True)

    p_strat = subparsers.add_parser("stratify")
    p_strat.add_argument("--rubric", required=True)
    p_strat.add_argument("--grading", required=True)

    p_opt = subparsers.add_parser("optimal-k")
    p_opt.add_argument("--rubric", required=True)
    p_opt.add_argument("--grading", required=True)
    p_opt.add_argument("--k", required=True, type=int)

    p_agree = subparsers.add_parser("agreement")
    p_agree.add_argument("--grading1", required=True)
    p_agree.add_argument("--grading2", required=True)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    {
        "score": cmd_score,
        "sensitivity": cmd_sensitivity,
        "stratify": cmd_stratify,
        "optimal-k": cmd_optimal_k,
        "agreement": cmd_agreement,
    }[args.command](args)


if __name__ == "__main__":
    main()
