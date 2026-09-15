"""Implement all four pipeline modules."""


# 1. data_loader.py -- load from SQLite with pricing pivot
data_loader_code = '''"""Load evaluation data from the SQLite database."""
import sqlite3


def load_from_sqlite(db_path):
    """Load and return (models, tasks, evaluations) from SQLite.

    Pivots the normalized pricing table into a dict per model.
    Converts SQLite integer booleans to Python bool.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Load models with pivoted pricing
    cur.execute("SELECT model_id, release_date, training_cutoff FROM models")
    models = []
    for row in cur.fetchall():
        model = dict(row)
        cur2 = conn.cursor()
        cur2.execute(
            "SELECT tier, price_per_mtok FROM pricing WHERE model_id = ?",
            (model["model_id"],),
        )
        tier_map = {
            "input": "input_per_mtok",
            "cached_input": "cached_input_per_mtok",
            "output": "output_per_mtok",
        }
        pricing = {}
        for pr in cur2.fetchall():
            pricing[tier_map[pr["tier"]]] = pr["price_per_mtok"]
        model["pricing"] = pricing
        models.append(model)

    # Load tasks
    cur.execute("SELECT task_id, repo, created_at FROM tasks")
    tasks = [dict(r) for r in cur.fetchall()]

    # Load evaluations grouped by (model_id, task_id)
    cur.execute(
        "SELECT model_id, task_id, run_id, resolved, "
        "input_tokens, cached_tokens, output_tokens "
        "FROM runs ORDER BY model_id, task_id, run_id"
    )
    eval_map = {}
    for row in cur.fetchall():
        key = (row["model_id"], row["task_id"])
        if key not in eval_map:
            eval_map[key] = {
                "model_id": row["model_id"],
                "task_id": row["task_id"],
                "runs": [],
            }
        eval_map[key]["runs"].append({
            "run_id": row["run_id"],
            "resolved": bool(row["resolved"]),
            "input_tokens": row["input_tokens"],
            "cached_tokens": row["cached_tokens"],
            "output_tokens": row["output_tokens"],
        })

    evaluations = list(eval_map.values())
    conn.close()
    return models, tasks, evaluations
'''

# 2. metrics.py -- correct candidates: combinatorial pass@k, Bessel SEM, tiered cost
metrics_code = '''"""Statistical metrics for benchmark evaluation."""
from math import comb, sqrt


def compute_pass_at_k(n, c, k):
    """Exact combinatorial (hypergeometric) pass@k estimator.

    pass@k = 1 - C(n-c, k) / C(n, k)
    """
    if n <= 0 or k <= 0:
        return 0.0
    if c < 0:
        c = 0
    if c > n:
        c = n
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
    """Tiered cost with cached token discount."""
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
'''

# 3. contamination.py
contamination_code = '''"""Data contamination detection."""
from datetime import datetime


def is_contaminated(task_created_at, model_release_date):
    """A task is contaminated if created strictly before the model release."""
    task_date = datetime.strptime(task_created_at, "%Y-%m-%d")
    release_date = datetime.strptime(model_release_date, "%Y-%m-%d")
    return task_date < release_date


def get_clean_task_ids(tasks, model_release_date):
    """Return task IDs not contaminated for the given model."""
    return [
        t["task_id"]
        for t in tasks
        if not is_contaminated(t["created_at"], model_release_date)
    ]
'''

# 4. ranking.py -- config-driven sort + unique solves
ranking_code = '''"""Model ranking with configurable sort criteria."""


def rank_models(model_results, ranking_config):
    """Rank models using sort criteria from the YAML config.

    ranking_config has:
      primary_sort: {field, order}
      tiebreakers: [{field, order}, ...]
    """
    primary = ranking_config["primary_sort"]
    tiebreakers = ranking_config.get("tiebreakers", [])

    def sort_key(x):
        keys = []
        val = x[primary["field"]]
        keys.append(-val if primary["order"] == "descending" else val)
        for tb in tiebreakers:
            val = x[tb["field"]]
            keys.append(-val if tb["order"] == "descending" else val)
        return tuple(keys)

    sorted_results = sorted(model_results, key=sort_key)
    for i, result in enumerate(sorted_results):
        result["rank"] = i + 1
    return sorted_results


def compute_unique_solves(evaluations, models):
    """Count tasks uniquely solved by each model."""
    task_solvers = {}
    for e in evaluations:
        if any(r["resolved"] for r in e["runs"]):
            task_solvers.setdefault(e["task_id"], set()).add(e["model_id"])

    counts = {m["model_id"]: 0 for m in models}
    for solvers in task_solvers.values():
        if len(solvers) == 1:
            counts[next(iter(solvers))] += 1
    return counts
'''

# Write all modules
with open("/app/pipeline/data_loader.py", "w") as f:
    f.write(data_loader_code)

with open("/app/pipeline/metrics.py", "w") as f:
    f.write(metrics_code)

with open("/app/pipeline/contamination.py", "w") as f:
    f.write(contamination_code)

with open("/app/pipeline/ranking.py", "w") as f:
    f.write(ranking_code)

print("All pipeline modules implemented.")
