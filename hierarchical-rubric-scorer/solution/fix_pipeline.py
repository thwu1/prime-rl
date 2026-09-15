#!/usr/bin/env python3
"""Fix all defects in the evaluation pipeline."""


LOADER_FIXED = '''\
"""Data loading and preprocessing for the evaluation pipeline."""

import json


def load_rubric(path):
    """Load rubric definition from JSON file."""
    with open(path) as f:
        return json.load(f)


def load_judgments(path):
    """Load judgment entries from JSONL file."""
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def deduplicate_and_filter(entries, valid_criterion_ids):
    """Deduplicate judgment entries and filter out invalid criteria.

    For entries sharing the same (sample_id, judge_id, criterion_id) key,
    retains the last occurrence (file order). Entries referencing criteria
    not present in the rubric are discarded.
    """
    deduped = {}
    for entry in entries:
        cid = entry["criterion_id"]
        if cid not in valid_criterion_ids:
            continue
        key = (entry["sample_id"], entry["judge_id"], cid)
        deduped[key] = entry["score"]
    return deduped
'''


SCORER_FIXED = '''\
"""Hierarchical scoring with dependency resolution."""


def build_criteria_graph(criteria_map):
    """Build topological ordering of criteria (children before parents)."""
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


def resolve_scores(aggregated, criteria_map, topo_order, sample_ids, threshold):
    """Process criteria in topological order: compute aggregates and resolve dependencies."""
    for sample_id in sample_ids:
        for crit_id in topo_order:
            crit = criteria_map[crit_id]

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

            for dep_id in crit.get("dependencies", []):
                if aggregated.get((sample_id, dep_id), 0.0) < threshold:
                    aggregated[(sample_id, crit_id)] = 0.0
                    break

    return aggregated
'''


METRICS_FIXED = '''\
"""Statistical metrics for evaluation quality assessment."""

import numpy as np


def compute_fleiss_kappa(scores_by_key, binary_ids, sample_ids, judge_ids):
    """Compute Fleiss\\' kappa for inter-rater reliability on binary criteria.

    Each (sample, binary_criterion) pair is treated as one subject.
    Each judge is one rater. The two categories are pass (>= 0.5)
    and fail (< 0.5).
    """
    n_raters = len(judge_ids)
    if n_raters < 2:
        return 0.0

    subjects = []
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
    """Compute bootstrap 95% confidence interval for the mean score.

    Uses numpy\\'s default_rng with the provided seed for reproducibility.
    Resamples with replacement and computes 2.5th/97.5th percentiles.
    """
    rng = np.random.default_rng(seed)
    arr = np.array(scores)
    boot_means = np.array([
        float(np.mean(rng.choice(arr, size=len(arr), replace=True)))
        for _ in range(n_resamples)
    ])
    return float(np.percentile(boot_means, 2.5)), float(np.percentile(boot_means, 97.5))
'''


def main():
    with open("/app/pipeline/loader.py", "w") as f:
        f.write(LOADER_FIXED)

    with open("/app/pipeline/scorer.py", "w") as f:
        f.write(SCORER_FIXED)

    with open("/app/pipeline/metrics.py", "w") as f:
        f.write(METRICS_FIXED)

    print("Pipeline fixes applied to loader.py, scorer.py, metrics.py")


if __name__ == "__main__":
    main()
