"""Database access layer for benchmark data."""
import sqlite3

DB_PATH = "/app/data/benchmark.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def load_model_data(model_name):
    """Load benchmark results for a model.
    Returns dict: (perturbation_id, task_id) -> successes
    """
    conn = get_connection()
    cursor = conn.execute(
        "SELECT perturbation_id, task_id, success_count FROM results WHERE model = ?",
        (model_name,)
    )
    data = {}
    for row in cursor:
        data[(row[0], row[1])] = row[2]
    conn.close()
    return data


def get_models():
    """Get sorted list of all model names."""
    conn = get_connection()
    cursor = conn.execute("SELECT DISTINCT model FROM results ORDER BY model")
    models = [row[0] for row in cursor]
    conn.close()
    return models


def get_perturbation_names():
    """Get mapping of perturbation_id -> perturbation_name."""
    conn = get_connection()
    cursor = conn.execute(
        "SELECT DISTINCT perturbation_id, perturbation_name "
        "FROM results ORDER BY perturbation_id"
    )
    mapping = {row[0]: row[1] for row in cursor}
    conn.close()
    return mapping


def get_total_rollouts():
    """Get the number of rollouts per cell."""
    conn = get_connection()
    cursor = conn.execute("SELECT total_rollouts FROM results LIMIT 1")
    result = cursor.fetchone()[0]
    conn.close()
    return result
