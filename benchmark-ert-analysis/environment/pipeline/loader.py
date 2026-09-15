"""Data loader for COCO benchmark experiment results from SQLite database."""
import json
import os
import sqlite3


def load_metadata(data_dir):
    """Load experimental metadata."""
    with open(os.path.join(data_dir, "metadata.json")) as f:
        return json.load(f)


def load_runs(db_path, algorithms):
    """Load and validate run data for all algorithms from SQLite.

    Applies standard validation to retain only confirmed instances.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    all_runs = {}

    for algo in algorithms:
        cursor = conn.execute(
            "SELECT r.id, r.function_id, r.dimension, r.instance, r.budget "
            "FROM runs r "
            "WHERE r.algorithm = ? AND r.instance <= 3 "
            "ORDER BY r.function_id, r.dimension, r.instance",
            (algo,)
        )
        runs = []
        for row in cursor:
            # Fetch targets reached for this run
            tcursor = conn.execute(
                "SELECT target, evals FROM targets_reached WHERE run_id = ?",
                (row["id"],)
            )
            targets = {t["target"]: t["evals"] for t in tcursor}
            runs.append({
                "function_id": row["function_id"],
                "dimension": row["dimension"],
                "instance": row["instance"],
                "budget": row["budget"],
                "targets_reached": targets,
            })
        all_runs[algo] = runs

    conn.close()
    return all_runs


def get_runs(all_runs, algo, func, dim):
    """Get runs for a specific (algorithm, function, dimension) combination."""
    return [r for r in all_runs[algo]
            if r["function_id"] == func and r["dimension"] == dim]
