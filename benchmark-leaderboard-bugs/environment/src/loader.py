"""Data loader for benchmark evaluation results."""
import json
import os


def load_models(data_dir):
    """Load model metadata."""
    with open(os.path.join(data_dir, "models.json")) as f:
        return json.load(f)


def load_tasks(data_dir):
    """Load task metadata."""
    with open(os.path.join(data_dir, "tasks.json")) as f:
        return json.load(f)


def load_run_results(data_dir, model_name, run_num):
    """Load results for a single run from JSONL file.

    Returns dict mapping instance_id to resolved status (bool).
    """
    path = os.path.join(data_dir, "runs", model_name, f"run_{run_num}.jsonl")
    results = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            results[entry["instance_id"]] = entry.get("resolved", False)
    return results


def load_all_runs(data_dir, model_name, num_runs=5):
    """Load all runs for a model."""
    runs = []
    for i in range(1, num_runs + 1):
        runs.append(load_run_results(data_dir, model_name, i))
    return runs
