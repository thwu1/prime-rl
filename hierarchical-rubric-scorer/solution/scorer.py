#!/usr/bin/env python3
"""
Hierarchical rubric scorer with dependency resolution, Fleiss' kappa,
and bootstrap confidence intervals.
"""

import json
import os
from collections import defaultdict

import numpy as np


def load_rubric(path):
    with open(path) as f:
        return json.load(f)


def load_judgments(path):
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def deduplicate_judgments(entries, valid_criterion_ids):
    """Keep the last entry per (sample_id, judge_id, criterion_id).
    Ignore entries with criterion_ids not in the rubric."""
    deduped = {}
    for entry in entries:
        cid = entry["criterion_id"]
        if cid not in valid_criterion_ids:
            continue
        key = (entry["sample_id"], entry["judge_id"], cid)
        deduped[key] = entry["score"]
    return deduped


def aggregate_judges(scores_by_key, criteria_map, sample_ids, judge_ids, leaf_ids):
    """Aggregate judge scores per leaf criterion per sample.
    Binary: majority vote. Partial: median."""
    aggregated = {}
    for sample_id in sample_ids:
        for crit_id in leaf_ids:
            judge_scores = []
            for judge_id in judge_ids:
                key = (sample_id, judge_id, crit_id)
                if key in scores_by_key:
                    judge_scores.append(scores_by_key[key])

            if not judge_scores:
                aggregated[(sample_id, crit_id)] = 0.0
                continue

            crit = criteria_map[crit_id]
            if crit["score_type"] == "binary":
                n_pass = sum(1 for s in judge_scores if s >= 0.5)
                aggregated[(sample_id, crit_id)] = 1.0 if n_pass > len(judge_scores) / 2 else 0.0
            elif crit["score_type"] == "partial":
                aggregated[(sample_id, crit_id)] = float(np.median(judge_scores))

    return aggregated


def topological_sort(criteria_map):
    """Topological sort: children and dependencies before the node itself."""
    visited = set()
    order = []

    def visit(node_id):
        if node_id in visited:
            return
        visited.add(node_id)
        node = criteria_map[node_id]
        for child_id in node.get("children", []):
            visit(child_id)
        for dep_id in node.get("dependencies", []):
            visit(dep_id)
        order.append(node_id)

    for crit_id in criteria_map:
        visit(crit_id)

    return order


def resolve_and_aggregate(aggregated, criteria_map, topo_order, sample_ids, threshold):
    """Process nodes in topological order: compute aggregates and apply dependencies."""
    for sample_id in sample_ids:
        for crit_id in topo_order:
            crit = criteria_map[crit_id]

            # Compute aggregate from children
            if crit["score_type"] == "aggregate":
                children = crit.get("children", [])
                if children:
                    total_weight = sum(criteria_map[c]["weight"] for c in children)
                    score = sum(
                        criteria_map[c]["weight"] * aggregated[(sample_id, c)]
                        for c in children
                    ) / total_weight
                else:
                    score = 0.0
                aggregated[(sample_id, crit_id)] = score

            # Apply dependency check
            for dep_id in crit.get("dependencies", []):
                if aggregated.get((sample_id, dep_id), 0.0) < threshold:
                    aggregated[(sample_id, crit_id)] = 0.0
                    break

    return aggregated


def compute_fleiss_kappa(scores_by_key, binary_ids, sample_ids, judge_ids):
    """Compute Fleiss' kappa on raw judge scores for binary criteria."""
    n_raters = len(judge_ids)
    if n_raters < 2:
        return 0.0

    subjects = []  # list of (n_pass, n_fail) tuples
    total_pass = 0
    total_ratings = 0

    for sample_id in sample_ids:
        for crit_id in binary_ids:
            n_pass = 0
            n_total = 0
            for judge_id in judge_ids:
                key = (sample_id, judge_id, crit_id)
                if key in scores_by_key:
                    n_total += 1
                    if scores_by_key[key] >= 0.5:
                        n_pass += 1
            n_fail = n_total - n_pass
            subjects.append((n_pass, n_fail, n_total))
            total_pass += n_pass
            total_ratings += n_total

    if total_ratings == 0:
        return 0.0

    # P_i for each subject
    p_i_list = []
    for n_pass, n_fail, n_total in subjects:
        if n_total <= 1:
            p_i_list.append(0.0)
        else:
            p_i = (n_pass ** 2 + n_fail ** 2 - n_total) / (n_total * (n_total - 1))
            p_i_list.append(p_i)

    p_bar = sum(p_i_list) / len(p_i_list)

    p_pass = total_pass / total_ratings
    p_fail = 1.0 - p_pass
    p_e = p_pass ** 2 + p_fail ** 2

    if abs(1.0 - p_e) < 1e-12:
        return 0.0

    return (p_bar - p_e) / (1.0 - p_e)


def compute_bootstrap_ci(scores, seed, n_resamples):
    """Bootstrap 95% CI for the mean."""
    rng = np.random.default_rng(seed)
    arr = np.array(scores)
    boot_means = np.array([
        np.mean(rng.choice(arr, size=len(arr), replace=True))
        for _ in range(n_resamples)
    ])
    return float(np.percentile(boot_means, 2.5)), float(np.percentile(boot_means, 97.5))


def main():
    rubric = load_rubric("/app/data/rubric.json")
    entries = load_judgments("/app/data/judgments.jsonl")

    criteria_map = {c["id"]: c for c in rubric["criteria"]}
    threshold = rubric["dependency_threshold"]
    bootstrap_seed = rubric["bootstrap_seed"]
    bootstrap_resamples = rubric["bootstrap_resamples"]

    valid_ids = set(criteria_map.keys())
    leaf_ids = [c["id"] for c in rubric["criteria"] if not c["children"]]
    binary_ids = [c["id"] for c in rubric["criteria"] if c["score_type"] == "binary"]

    # Deduplicate and filter
    scores_by_key = deduplicate_judgments(entries, valid_ids)

    # Discover sample_ids and judge_ids from the cleaned data
    sample_ids = sorted({k[0] for k in scores_by_key})
    judge_ids = sorted({k[1] for k in scores_by_key})

    # Step 1: aggregate judges for leaf criteria
    aggregated = aggregate_judges(scores_by_key, criteria_map, sample_ids, judge_ids, leaf_ids)

    # Step 2: topological sort
    topo_order = topological_sort(criteria_map)

    # Step 3: resolve dependencies and compute aggregates
    aggregated = resolve_and_aggregate(
        aggregated, criteria_map, topo_order, sample_ids, threshold
    )

    # Compute outputs
    sample_scores = {sid: aggregated[(sid, "root")] for sid in sample_ids}
    mean_score = sum(sample_scores.values()) / len(sample_scores)

    all_crit_ids = [c["id"] for c in rubric["criteria"]]
    criterion_means = {}
    for cid in all_crit_ids:
        vals = [aggregated[(sid, cid)] for sid in sample_ids]
        criterion_means[cid] = sum(vals) / len(vals)

    fleiss_kappa = compute_fleiss_kappa(scores_by_key, binary_ids, sample_ids, judge_ids)

    scores_list = [sample_scores[sid] for sid in sorted(sample_ids)]
    ci_lower, ci_upper = compute_bootstrap_ci(scores_list, bootstrap_seed, bootstrap_resamples)

    output = {
        "sample_scores": sample_scores,
        "mean_score": mean_score,
        "criterion_means": criterion_means,
        "fleiss_kappa": fleiss_kappa,
        "bootstrap_ci_lower": ci_lower,
        "bootstrap_ci_upper": ci_upper,
    }

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/scores.json", "w") as f:
        json.dump(output, f, indent=2)

    print("Scores written to /app/output/scores.json")


if __name__ == "__main__":
    main()
