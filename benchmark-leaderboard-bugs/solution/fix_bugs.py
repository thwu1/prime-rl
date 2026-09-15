#!/usr/bin/env python3
"""Fix all bugs in the benchmark evaluation pipeline.

Bug 1 (metrics.py): resolved_rate_per_run divides by count of present entries
       instead of total task count. Missing entries are silently ignored.
Bug 2 (metrics.py): SEM uses population variance (/ n) instead of sample
       variance (/ (n-1)) for Bessel's correction.
Bug 3 (metrics.py): pass@k uses the naive biased formula 1-(1-c/n)^k instead
       of the unbiased estimator 1 - C(n-c,k)/C(n,k).
Bug 4 (contamination.py): uses <= instead of < for date comparison, wrongly
       flagging tasks created on the same day as the model release.
Bug 5 (analyzer.py): time-window filtering via --start-date / --end-date is
       not implemented; the arguments are accepted but never applied.
"""

METRICS_PY = '''\
"""Statistical metrics for benchmark evaluation."""
import math


def resolved_rate_per_run(run_results, task_ids):
    """Compute fraction of tasks resolved in a single run.
    Missing tasks count as not resolved; denominator is always total tasks."""
    resolved = sum(1 for tid in task_ids if run_results.get(tid, False))
    return resolved / len(task_ids)


def compute_resolved_rate(runs, task_ids):
    """Compute mean resolved rate across all runs."""
    rates = [resolved_rate_per_run(run, task_ids) for run in runs]
    return sum(rates) / len(rates)


def compute_sem(runs, task_ids):
    """Compute standard error of the mean using sample std (n-1 denominator)."""
    rates = [resolved_rate_per_run(run, task_ids) for run in runs]
    mean = sum(rates) / len(rates)
    n = len(rates)
    sample_variance = sum((r - mean) ** 2 for r in rates) / (n - 1)
    return math.sqrt(sample_variance) / math.sqrt(n)


def compute_pass_at_k(runs, task_ids, k):
    """Compute pass@k using the unbiased estimator: 1 - C(n-c,k)/C(n,k)."""
    n = len(runs)
    if k > n:
        raise ValueError(f"k={k} exceeds number of runs n={n}")

    pass_k_per_task = []
    for tid in task_ids:
        c = sum(1 for run in runs if run.get(tid, False))
        if n - c < k:
            pass_k = 1.0
        else:
            pass_k = 1.0 - math.comb(n - c, k) / math.comb(n, k)
        pass_k_per_task.append(pass_k)

    return sum(pass_k_per_task) / len(pass_k_per_task)
'''

CONTAMINATION_PY = '''\
"""Contamination detection for benchmark evaluation."""


def is_contaminated(task_created_at, model_release_date):
    """Check if a task is potentially contaminated for a given model.

    A task is contaminated if it was created strictly before the model release.
    Same-day creation is NOT considered contaminated.
    """
    return task_created_at < model_release_date


def count_contaminated_tasks(tasks, model_release_date):
    """Count tasks potentially contaminated for a model."""
    return sum(
        1 for t in tasks if is_contaminated(t["created_at"], model_release_date)
    )
'''

ANALYZER_PY = '''\
"""Main analyzer for benchmark evaluation."""
from loader import load_models, load_tasks, load_all_runs
from metrics import compute_resolved_rate, compute_sem, compute_pass_at_k
from contamination import count_contaminated_tasks


class Analyzer:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.models = load_models(data_dir)
        self.tasks = load_tasks(data_dir)

    def compute_leaderboard(self, start_date=None, end_date=None):
        """Compute the full leaderboard."""
        # Apply time-window filtering
        tasks = self.tasks
        if start_date is not None:
            tasks = [t for t in tasks if t["created_at"] >= start_date]
        if end_date is not None:
            tasks = [t for t in tasks if t["created_at"] <= end_date]

        task_ids = [t["id"] for t in tasks]

        rankings = []
        for model in self.models:
            runs = load_all_runs(self.data_dir, model["name"])

            resolved_rate = compute_resolved_rate(runs, task_ids)
            sem = compute_sem(runs, task_ids)
            pass_at_1 = compute_pass_at_k(runs, task_ids, 1)
            pass_at_3 = compute_pass_at_k(runs, task_ids, 3)
            pass_at_5 = compute_pass_at_k(runs, task_ids, 5)

            num_contaminated = count_contaminated_tasks(
                tasks, model["release_date"]
            )

            rankings.append({
                "model": model["name"],
                "resolved_rate": round(resolved_rate, 5),
                "sem": round(sem, 5),
                "pass_at_1": round(pass_at_1, 5),
                "pass_at_3": round(pass_at_3, 5),
                "pass_at_5": round(pass_at_5, 5),
                "num_contaminated_tasks": num_contaminated,
                "contamination_fraction": round(
                    num_contaminated / len(task_ids), 5
                ) if task_ids else 0,
            })

        rankings.sort(key=lambda x: x["resolved_rate"], reverse=True)

        for i, r in enumerate(rankings):
            r["rank"] = i + 1

        task_difficulty = self._compute_task_difficulty(task_ids)

        return {
            "time_window": {
                "start": start_date,
                "end": end_date,
            },
            "num_tasks": len(task_ids),
            "num_runs_per_model": 5,
            "rankings": rankings,
            "task_difficulty": task_difficulty,
        }

    def _compute_task_difficulty(self, task_ids):
        """Compute difficulty metrics for each task."""
        difficulties = []
        for tid in task_ids:
            solve_rates = []
            num_solved = 0
            for model in self.models:
                runs = load_all_runs(self.data_dir, model["name"])
                c = sum(1 for run in runs if run.get(tid, False))
                solve_rates.append(c / len(runs))
                if c > 0:
                    num_solved += 1

            difficulties.append({
                "task_id": tid,
                "mean_solve_rate": round(
                    sum(solve_rates) / len(solve_rates), 5
                ),
                "num_models_solved_at_least_once": num_solved,
            })

        difficulties.sort(key=lambda x: x["mean_solve_rate"])

        return difficulties
'''


def main():
    with open("/app/src/metrics.py", "w") as f:
        f.write(METRICS_PY)

    with open("/app/src/contamination.py", "w") as f:
        f.write(CONTAMINATION_PY)

    with open("/app/src/analyzer.py", "w") as f:
        f.write(ANALYZER_PY)

    print("All bugs fixed in metrics.py, contamination.py, and analyzer.py")


if __name__ == "__main__":
    main()
