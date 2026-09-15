#!/usr/bin/env python3
"""Reference implementation of the code evaluation pipeline."""
import ast
import json
import multiprocessing
import os
import re
import sqlite3
from collections import defaultdict


def get_config(db_path):
    """Read configuration from the database."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT key, value FROM config")
    raw = dict(c.fetchall())
    conn.close()
    return {
        "temporal_cutoff": raw["temporal_cutoff"],
        "timeout_seconds": int(raw["timeout_seconds"]),
        "k_values": [int(x) for x in raw["k_values"].split(",")],
    }


def get_problems(db_path, cutoff_date):
    """Read problems released on or after the cutoff date."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT * FROM problems WHERE release_date >= ?",
        (cutoff_date,),
    )
    problems = {row["task_id"]: dict(row) for row in c.fetchall()}
    conn.close()
    return problems


def get_predictions(db_path, task_ids):
    """Read predictions for the given task IDs, grouped by model and task."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    placeholders = ",".join("?" * len(task_ids))
    c.execute(
        f"SELECT * FROM predictions WHERE task_id IN ({placeholders})",
        list(task_ids),
    )
    preds = defaultdict(lambda: defaultdict(list))
    for row in c.fetchall():
        preds[row["model_name"]][row["task_id"]].append(dict(row))
    conn.close()
    return preds


def extract_code(model_output):
    """Extract Python code from raw LLM output.

    Handles markdown-fenced code blocks and bare code.
    Picks the longest syntactically valid block when multiple are found.
    """
    # Try ```python blocks first
    pattern = r"```python\s*\n(.*?)```"
    blocks = re.findall(pattern, model_output, re.DOTALL)

    if not blocks:
        # Try generic ``` blocks
        pattern = r"```\s*\n(.*?)```"
        blocks = re.findall(pattern, model_output, re.DOTALL)

    if blocks:
        valid_blocks = []
        for block in blocks:
            block = block.strip()
            try:
                ast.parse(block)
                valid_blocks.append(block)
            except SyntaxError:
                pass
        if valid_blocks:
            valid_blocks.sort(key=lambda x: len(x.split("\n")))
            return valid_blocks[-1]

    # Fallback: find longest valid Python substring
    lines = model_output.split("\n")
    best = ""
    best_len = 0
    for i in range(len(lines)):
        for j in range(i + 1, len(lines) + 1):
            candidate = "\n".join(lines[i:j])
            try:
                ast.parse(candidate)
                num_nonblank = sum(1 for line in lines[i:j] if line.strip())
                if num_nonblank > best_len:
                    best_len = num_nonblank
                    best = candidate
            except SyntaxError:
                pass
    return best


def _worker(prog, res):
    """Execute a check program and report result."""
    try:
        exec_globals = {}
        exec(prog, exec_globals)
        res.append("passed")
    except Exception as e:
        res.append(f"failed: {type(e).__name__}: {e}")


def run_check(check_program, timeout=5.0):
    """Execute a check program in an isolated subprocess with timeout."""
    manager = multiprocessing.Manager()
    result = manager.list()

    p = multiprocessing.Process(target=_worker, args=(check_program, result))
    p.start()
    p.join(timeout=timeout)

    if p.is_alive():
        p.kill()
        p.join()

    if not result:
        return "timed out"
    return result[0]


def estimate_pass_at_k(n, c, k):
    """Unbiased estimator: pass@k = 1 - C(n-c,k) / C(n,k).

    Uses the product form for numerical stability.
    """
    if n - c < k:
        return 1.0
    product = 1.0
    for i in range(n - c + 1, n + 1):
        product *= 1.0 - k / i
    return 1.0 - product


def main():
    db_path = "/app/benchmark.db"

    # Read configuration
    config = get_config(db_path)

    # Read filtered problems
    problems = get_problems(db_path, config["temporal_cutoff"])

    # Read predictions for filtered problems only
    predictions = get_predictions(db_path, problems.keys())

    # Evaluate each model
    model_results = {}
    for model_name, model_preds in predictions.items():
        per_problem = {}
        for task_id, problem in problems.items():
            preds = model_preds.get(task_id, [])
            total = len(preds)
            correct = 0

            for pred in preds:
                code = extract_code(pred["model_output"])
                check_program = (
                    problem["prompt"]
                    + "\n"
                    + code
                    + "\n"
                    + problem["test_code"]
                    + "\n"
                    + f"check({problem['entry_point']})"
                )
                result = run_check(check_program, timeout=config["timeout_seconds"])
                if result == "passed":
                    correct += 1

            per_problem[task_id] = {"total": total, "correct": correct}

        # Compute pass@k
        pass_at = {}
        for k in config["k_values"]:
            scores = []
            for task_id in problems:
                n = per_problem[task_id]["total"]
                c = per_problem[task_id]["correct"]
                scores.append(estimate_pass_at_k(n, c, k))
            pass_at[k] = sum(scores) / len(scores)

        model_results[model_name] = {
            "per_problem": per_problem,
            "pass_at": pass_at,
        }

    # Build leaderboard sorted by pass@1 descending
    sorted_models = sorted(
        model_results.items(),
        key=lambda x: x[1]["pass_at"][1],
        reverse=True,
    )

    leaderboard = {
        "config": config,
        "models": [],
    }

    for rank, (model_name, data) in enumerate(sorted_models, 1):
        entry = {
            "rank": rank,
            "model_name": model_name,
            "num_problems": len(problems),
        }
        for k in config["k_values"]:
            entry[f"pass@{k}"] = data["pass_at"][k]
        entry["per_problem"] = data["per_problem"]
        leaderboard["models"].append(entry)

    # Write output
    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/leaderboard.json", "w") as f:
        json.dump(leaderboard, f, indent=2)

    print("Leaderboard generated.")
    for entry in leaderboard["models"]:
        print(
            f"  #{entry['rank']} {entry['model_name']}: "
            f"pass@1={entry['pass@1']:.4f}"
        )


if __name__ == "__main__":
    main()
