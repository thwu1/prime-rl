#!/usr/bin/env python3
"""Compute evaluation metrics from extracted data.

Usage: python3 compute_metrics.py <extracted.json> <config.yaml>
Outputs: metrics JSON array to stdout.
"""
import json
import sys
from math import comb, sqrt

import yaml


def compute_pass_at_k(n, c, k):
    """Exact combinatorial (hypergeometric) pass@k estimator.

    pass@k = 1 - C(n-c, k) / C(n, k)
    """
    if n <= 0 or k <= 0:
        return 0.0
    c = max(0, min(c, n))
    if k > n:
        return 1.0 if c > 0 else 0.0
    denom = comb(n, k)
    if denom == 0:
        return 1.0 if c > 0 else 0.0
    return 1.0 - comb(n - c, k) / denom


def compute_sem(successes, total):
    """SEM with Bessel's correction: sqrt(p*(1-p)/(n-1))."""
    if total <= 1:
        return 0.0
    p = successes / total
    if p == 0.0 or p == 1.0:
        return 0.0
    return sqrt(p * (1.0 - p) / (total - 1))


def compute_cost_per_problem(runs, pricing):
    """Tiered cost with cached token discount, averaged over runs."""
    if not runs:
        return 0.0
    total = 0.0
    for r in runs:
        uncached = r["input_tokens"] - r["cached_tokens"]
        total += (
            uncached * pricing["input_per_mtok"]
            + r["cached_tokens"] * pricing["cached_input_per_mtok"]
            + r["output_tokens"] * pricing["output_per_mtok"]
        ) / 1_000_000
    return total / len(runs)


def is_contaminated(task_created_at, model_release_date):
    """A task is contaminated if created strictly before the model release."""
    return task_created_at < model_release_date


def get_clean_task_ids(tasks, model_release_date):
    """Return task IDs not contaminated for the given model."""
    return [
        t["task_id"]
        for t in tasks
        if not is_contaminated(t["created_at"], model_release_date)
    ]


def compute_unique_solves(evaluations, models):
    """Count tasks uniquely solved by each model (any run resolved)."""
    task_solvers = {}
    for e in evaluations:
        if any(r["resolved"] for r in e["runs"]):
            task_solvers.setdefault(e["task_id"], set()).add(e["model_id"])

    counts = {m["model_id"]: 0 for m in models}
    for solvers in task_solvers.values():
        if len(solvers) == 1:
            counts[next(iter(solvers))] += 1
    return counts


def main():
    data = json.load(open(sys.argv[1]))
    config = yaml.safe_load(open(sys.argv[2]))
    k = config["pipeline"]["k"]

    models = data["models"]
    tasks = data["tasks"]
    evaluations = data["evaluations"]

    model_results = []
    for model in models:
        model_id = model["model_id"]
        model_evals = [e for e in evaluations if e["model_id"] == model_id]

        all_runs = []
        task_pk = []
        for ev in model_evals:
            runs = ev["runs"]
            all_runs.extend(runs)
            n = len(runs)
            c = sum(1 for r in runs if r["resolved"])
            task_pk.append(compute_pass_at_k(n, c, k))

        total_runs = len(all_runs)
        total_succ = sum(1 for r in all_runs if r["resolved"])
        resolved_rate = total_succ / total_runs if total_runs else 0
        sem = compute_sem(total_succ, total_runs)
        avg_pk = sum(task_pk) / len(task_pk) if task_pk else 0
        cost = compute_cost_per_problem(all_runs, model["pricing"])

        clean_ids = get_clean_task_ids(tasks, model["release_date"])
        contaminated_count = len(tasks) - len(clean_ids)

        decontam_evals = [e for e in model_evals if e["task_id"] in clean_ids]
        decontam_runs = [r for e in decontam_evals for r in e["runs"]]
        decontam_total = len(decontam_runs)
        decontam_succ = sum(1 for r in decontam_runs if r["resolved"])
        decontam_rate = decontam_succ / decontam_total if decontam_total else 0

        model_results.append({
            "model_id": model_id,
            "resolved_rate": resolved_rate,
            "sem": sem,
            "pass_at_k": avg_pk,
            "cost_per_problem": cost,
            "contaminated_count": contaminated_count,
            "decontaminated_resolved_rate": decontam_rate,
        })

    unique = compute_unique_solves(evaluations, models)
    for r in model_results:
        r["unique_solves"] = unique.get(r["model_id"], 0)

    json.dump(model_results, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
