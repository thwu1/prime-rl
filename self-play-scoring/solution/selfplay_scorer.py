#!/usr/bin/env python3

"""
Self-play patch selection scorer.

Implements the test-time self-play scoring algorithm for selecting the optimal
BugFixer patch using TestWriter cross-evaluation results.
"""

import json
import os
import glob
import sys


def load_instances(data_dir):
    """Load all instance JSON files from the instances directory."""
    instances_dir = os.path.join(data_dir, "instances")
    instances = []
    for fpath in sorted(glob.glob(os.path.join(instances_dir, "*.json"))):
        with open(fpath) as f:
            instances.append(json.load(f))
    return instances


def score_instance(instance):
    """Compute self-play scores for all bug patches in an instance."""
    instance_id = instance["instance_id"]
    bug_patches = instance["bug_patches"]
    test_patches = instance["test_patches"]
    test_results = instance["test_results_unpatched"]
    exec_matrix = instance["execution_matrix"]

    # Step 1: Filter valid tests
    valid_tests = [
        tid for tid, tinfo in test_patches.items()
        if tinfo.get("fails_on_original", False)
    ]

    # Step 2: Compute sum_F and sum_P across valid tests
    sum_f = 0.0
    sum_p = 0.0
    for tj in valid_tests:
        tr = test_results.get(tj, {})
        sum_f += tr.get("failed", 0)
        sum_p += tr.get("passed", 0)

    # Step 3: Compute S_i for each bug patch
    scores = {}
    for bi in bug_patches:
        fp_sum = 0.0
        pp_sum = 0.0
        bi_matrix = exec_matrix.get(bi, {})
        for tj in valid_tests:
            entry = bi_matrix.get(tj, {})
            fp_sum += entry.get("fail_to_pass", 0)
            pp_sum += entry.get("pass_to_pass", 0)

        fp_term = fp_sum / sum_f if sum_f > 0 else 0.0
        pp_term = pp_sum / sum_p if sum_p > 0 else 0.0
        scores[bi] = fp_term + pp_term

    # Step 4: Rank - sort by score descending, then patch_id ascending
    ranking = sorted(scores.items(), key=lambda x: (-x[1], x[0]))

    selected_patch = ranking[0][0]
    selected_score = ranking[0][1]

    return {
        "instance_id": instance_id,
        "selected_patch": selected_patch,
        "score": selected_score,
        "ranking": [
            {"patch_id": pid, "score": s} for pid, s in ranking
        ],
    }


def main():
    data_dir = "/app/data"
    output_path = "/app/results.json"

    instances = load_instances(data_dir)

    results = []
    for inst in instances:
        result = score_instance(inst)
        results.append(result)

    # Sort results by instance_id
    results.sort(key=lambda r: r["instance_id"])

    with open(output_path, "w") as f:
        json.dump({"results": results}, f, indent=2)

    print(f"Wrote results for {len(results)} instances to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
