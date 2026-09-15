#!/usr/bin/env python3
"""Compute evaluation metrics from extracted data.

Usage: python3 compute_metrics.py <extracted.json> <config.yaml>
Outputs: metrics JSON array to stdout.

Each element: {model_id, resolved_rate, sem, pass_at_k, cost_per_problem,
               contaminated_count, decontaminated_resolved_rate, unique_solves}

Study the candidate implementations in /app/candidates/ and the methodology
notes in /app/docs/methodology.md to determine the correct statistical
approach for each metric. Functions must be importable at module level.
"""
import sys


def compute_pass_at_k(n, c, k):
    """Compute pass@k for n total runs with c successes, sampling k."""
    raise NotImplementedError


def compute_sem(successes, total):
    """Compute standard error of the mean for a binary outcome."""
    raise NotImplementedError


def compute_cost_per_problem(runs, pricing):
    """Compute average cost per problem from runs and pricing dict."""
    raise NotImplementedError


def is_contaminated(task_created_at, model_release_date):
    """Return True if the task is contaminated for the given model."""
    raise NotImplementedError


def get_clean_task_ids(tasks, model_release_date):
    """Return list of task IDs not contaminated for the given model."""
    raise NotImplementedError


def compute_unique_solves(evaluations, models):
    """Return dict mapping model_id to count of uniquely solved tasks."""
    raise NotImplementedError


def main():
    raise NotImplementedError("Implement metric computation pipeline")


if __name__ == "__main__":
    main()
