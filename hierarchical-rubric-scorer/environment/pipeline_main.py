#!/usr/bin/env python3
"""Main entry point for the evaluation pipeline."""

import json
import os

from pipeline.loader import load_rubric, load_judgments, deduplicate_and_filter
from pipeline.aggregator import aggregate_judge_scores
from pipeline.scorer import build_criteria_graph, resolve_scores
from pipeline.metrics import compute_fleiss_kappa, compute_bootstrap_ci


def main():
    rubric = load_rubric("/app/data/rubric.json")
    entries = load_judgments("/app/data/judgments.jsonl")

    criteria_map = {c["id"]: c for c in rubric["criteria"]}
    config = {
        "threshold": rubric["dependency_threshold"],
        "bootstrap_seed": rubric["bootstrap_seed"],
        "bootstrap_resamples": rubric["bootstrap_resamples"],
    }

    valid_ids = set(criteria_map.keys())
    scores_by_key = deduplicate_and_filter(entries, valid_ids)

    sample_ids = sorted({k[0] for k in scores_by_key})
    judge_ids = sorted({k[1] for k in scores_by_key})

    leaf_ids = [c["id"] for c in rubric["criteria"] if not c["children"]]
    binary_ids = [c["id"] for c in rubric["criteria"] if c["score_type"] == "binary"]

    aggregated = aggregate_judge_scores(
        scores_by_key, criteria_map, sample_ids, judge_ids, leaf_ids
    )

    topo_order = build_criteria_graph(criteria_map)
    aggregated = resolve_scores(
        aggregated, criteria_map, topo_order, sample_ids, config["threshold"]
    )

    sample_scores = {sid: aggregated[(sid, "root")] for sid in sample_ids}
    mean_score = sum(sample_scores.values()) / len(sample_scores)

    all_crit_ids = [c["id"] for c in rubric["criteria"]]
    criterion_means = {}
    for cid in all_crit_ids:
        vals = [aggregated[(sid, cid)] for sid in sample_ids]
        criterion_means[cid] = sum(vals) / len(vals)

    fleiss_kappa = compute_fleiss_kappa(scores_by_key, binary_ids, sample_ids, judge_ids)

    scores_list = [sample_scores[sid] for sid in sorted(sample_ids)]
    ci_lower, ci_upper = compute_bootstrap_ci(
        scores_list, config["bootstrap_seed"], config["bootstrap_resamples"]
    )

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
