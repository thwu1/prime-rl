#!/usr/bin/env python3

"""
TypeSim evaluation engine implementation.
"""

import json
import math
import os
from collections import defaultdict

import numpy as np
from scipy.optimize import linear_sum_assignment


# ---- Load data ----

def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


# ---- Type tree utilities ----

def str_repr(t):
    """Compute canonical string representation of a type tree."""
    kind = t["kind"]
    if kind == "Instance":
        origin = t["origin"]
        args = t.get("args", [])
        if not args:
            return origin
        return origin + "[" + ", ".join(str_repr(a) for a in args) + "]"
    elif kind == "Any":
        return "Any"
    elif kind == "None":
        return "None"
    elif kind == "Union":
        return "Union[" + ", ".join(str_repr(i) for i in t["items"]) + "]"
    elif kind == "Tuple":
        return "tuple[" + ", ".join(str_repr(i) for i in t["items"]) + "]"
    else:
        raise ValueError(f"Unknown type kind: {kind}")


def analyze_type(t):
    """Extract (name, origin_key, type_args) from a non-Union type."""
    kind = t["kind"]
    if kind == "Instance":
        return (t["origin"], t["origin"], t.get("args", []))
    elif kind == "Any":
        return ("Any", "Any", [])
    elif kind == "None":
        return ("None", "None", [])
    elif kind == "Tuple":
        return ("tuple", "tuple", t["items"])
    else:
        raise ValueError(f"Cannot analyze type kind: {kind}")


def get_type_meta(t):
    """Compute (depth, count) metadata for a type tree."""
    meta_depth = 1
    meta_count = 0

    if t["kind"] == "Union":
        for item in t["items"]:
            child_depth, child_count = get_type_meta(item)
            meta_depth = max(meta_depth, child_depth + 1)
            meta_count += child_count
    else:
        _name, _origin, type_args = analyze_type(t)
        for arg in type_args:
            child_depth, child_count = get_type_meta(arg)
            meta_depth = max(meta_depth, child_depth + 1)
            meta_count += child_count

    meta_count += 1
    return (meta_depth, meta_count)


# ---- Attribute similarity ----

class AttributeRegistry:
    def __init__(self, registry_data):
        self.base_attributes = set(registry_data["base_attributes"])
        self.types = {k: set(v) for k, v in registry_data["types"].items()}

    def get_type_attributes(self, origin_key):
        return self.types[origin_key]

    def get_base_attributes(self):
        return self.base_attributes


def _get_type_info_similarity(registry, a_origin, b_origin):
    """Compute attribute-based similarity between two type origins."""
    a_attrs = registry.get_type_attributes(a_origin)
    b_attrs = registry.get_type_attributes(b_origin)
    base = registry.get_base_attributes()

    a_minus_b = a_attrs - b_attrs
    b_minus_a = b_attrs - a_attrs
    common = a_attrs & b_attrs

    numerator = len(a_minus_b) + len(b_minus_a)
    denominator = len(common - base) + len(a_minus_b) + len(b_minus_a)

    if denominator == 0 and numerator == 0:
        return 1.0
    return 1.0 - numerator / denominator


# ---- Type similarity ----

def compare_within_level(registry, a_list, b_list, is_union):
    """Compare two lists of types, using Hungarian matching for unions."""
    if is_union:
        n_b = len(b_list)
        n_a = len(a_list)
        cost_matrix = np.empty((n_b, n_a))
        for i in range(n_b):
            for j in range(n_a):
                cost_matrix[i, j] = get_type_similarity(registry, b_list[i], a_list[j])

        row_ind, col_ind = linear_sum_assignment(-cost_matrix)
        score = cost_matrix[row_ind, col_ind].sum()
    else:
        score = 0.0
        for i in range(min(len(a_list), len(b_list))):
            score += get_type_similarity(registry, a_list[i], b_list[i])

    score /= max(len(a_list), len(b_list))
    return score


def get_type_similarity(registry, a_type, b_type):
    """Compute recursive structural similarity between two types."""
    a_is_union = a_type["kind"] == "Union"
    b_is_union = b_type["kind"] == "Union"

    # Union dispatch
    if a_is_union and not b_is_union:
        return compare_within_level(registry, a_type["items"], [b_type], is_union=True)
    if not a_is_union and b_is_union:
        return compare_within_level(registry, [a_type], b_type["items"], is_union=True)
    if a_is_union and b_is_union:
        return compare_within_level(registry, a_type["items"], b_type["items"], is_union=True)

    # Neither is Union
    a_name, a_origin, a_args = analyze_type(a_type)
    b_name, b_origin, b_args = analyze_type(b_type)

    # Short-circuit for identical string representations
    if str_repr(a_type) == str_repr(b_type):
        score = 1.0
    else:
        score = _get_type_info_similarity(registry, a_origin, b_origin)

    # Recurse into type arguments
    if a_args and b_args:
        score = (score + compare_within_level(registry, a_args, b_args, is_union=False)) / 2.0
    elif a_args or b_args:
        score = score / 2.0

    return score


# ---- Repository evaluation ----

def compare_type_info(registry, gt_types, pred_types, baseline_types):
    """Evaluate predicted types against ground truth with baseline filtering."""
    score_dict = {}
    missing_vars = set()
    meta_dict = {}

    for var_name, gt_type in gt_types.items():
        # Skip if ground truth is Any
        if gt_type["kind"] == "Any":
            continue

        # Skip if in baseline with non-Any type
        if var_name in baseline_types and baseline_types[var_name]["kind"] != "Any":
            continue

        meta_dict[var_name] = get_type_meta(gt_type)

        if var_name in pred_types:
            score_dict[var_name] = get_type_similarity(registry, gt_type, pred_types[var_name])
        else:
            score_dict[var_name] = 0.0
            missing_vars.add(var_name)

    return score_dict, missing_vars, meta_dict


def compute_consistency_score(num_errors, num_vars):
    """Compute type-checking consistency from mypy error counts."""
    return math.exp(-num_errors / num_vars * 10)


def compute_scores_by_depth(score_dict, meta_dict):
    """Group scores by type depth and compute per-depth averages."""
    by_depth = defaultdict(list)
    for var_name, score in score_dict.items():
        depth = min(meta_dict[var_name][0], 5)  # cap at 5
        by_depth[depth].append(score)

    result = {}
    for depth, scores in sorted(by_depth.items()):
        result[str(depth)] = sum(scores) / len(scores) if scores else 0.0
    return result


# ---- Main ----

def main():
    # Load data
    registry_data = load_json("/app/data/attribute_registry.json")
    registry = AttributeRegistry(registry_data)

    type_pairs = load_json("/app/data/type_pairs.json")
    meta_types = load_json("/app/data/meta_types.json")
    gt_data = load_json("/app/data/repo_ground_truth.json")
    pred_data = load_json("/app/data/repo_predicted.json")
    baseline_data = load_json("/app/data/repo_baseline.json")

    # 1. Pairwise similarity scores
    pair_scores = {}
    for pair in type_pairs:
        pair_id = pair["id"]
        score = get_type_similarity(registry, pair["type_a"], pair["type_b"])
        pair_scores[pair_id] = score

    # 2. Type metadata
    type_meta = {}
    for meta_entry in meta_types:
        meta_id = meta_entry["id"]
        depth, count = get_type_meta(meta_entry["type"])
        type_meta[meta_id] = {"depth": depth, "count": count}

    # 3. Repository evaluation
    score_dict, missing_vars, meta_dict = compare_type_info(
        registry,
        gt_data["types"],
        pred_data["types"],
        baseline_data["types"]
    )

    total_count = len(score_dict)
    missing_count = len(missing_vars)
    overall_score = sum(score_dict.values()) / total_count if total_count > 0 else 0.0

    if total_count > missing_count:
        overall_score_wo_missing = overall_score * total_count / (total_count - missing_count)
    else:
        overall_score_wo_missing = 0.0

    scores_by_depth = compute_scores_by_depth(score_dict, meta_dict)

    consistency_gt = compute_consistency_score(gt_data["filtered_error_count"], total_count)
    consistency_pred = compute_consistency_score(pred_data["filtered_error_count"], total_count)

    # Build output
    results = {
        "pair_scores": pair_scores,
        "type_meta": type_meta,
        "repo_evaluation": {
            "overall_score": overall_score,
            "overall_score_without_missing": overall_score_wo_missing,
            "missing_count": missing_count,
            "total_count": total_count,
            "scores_by_depth": scores_by_depth,
            "consistency_score_gt": consistency_gt,
            "consistency_score_pred": consistency_pred
        }
    }

    # Write output
    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/output/results.json")


if __name__ == "__main__":
    main()
