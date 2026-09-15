#!/usr/bin/env python3
"""Benchmark evaluation pipeline orchestrator.

Multi-stage pipeline:
  Stage 1: DuckDB SQL extraction (extract.sql) - reads Parquet + SQLite data
  Stage 2: Python transform (transform.py) - computes pass@k and contamination
  Stage 3: jq assembly (assemble.jq) - produces final JSON output

See /app/docs/spec.md for the full specification.
"""
import argparse
import json
import os
import subprocess
import sys

import duckdb


SRC_DIR = os.path.dirname(os.path.abspath(__file__))


def stage_extract(data_dir, output_path):
    """Stage 1: Run DuckDB SQL extraction over Parquet + SQLite data."""
    with open(os.path.join(SRC_DIR, "extract.sql")) as f:
        sql = f.read()

    db_path = os.path.join(data_dir, "benchmark.db")
    runs_dir = os.path.join(data_dir, "runs")

    sql = sql.replace("{db_path}", db_path)
    sql = sql.replace("{runs_dir}", runs_dir)

    conn = duckdb.connect()
    for statement in sql.split(";"):
        statement = statement.strip()
        if statement:
            conn.execute(statement)

    # Read results from temp tables
    model_metrics = conn.execute(
        "SELECT model_name, resolved_rate, sem FROM model_metrics"
    ).fetchall()

    task_solve = conn.execute(
        "SELECT instance_id, model_name, successes, attempts "
        "FROM task_solve_counts"
    ).fetchall()

    run_results = conn.execute(
        "SELECT model_name, instance_id, run_name, resolved "
        "FROM long_results"
    ).fetchall()

    tasks = conn.execute("SELECT id, created_at, repo FROM task_info").fetchall()
    models = conn.execute("SELECT name, release_date FROM model_info").fetchall()
    meta = conn.execute(
        "SELECT num_tasks, num_runs_per_model FROM pipeline_meta"
    ).fetchone()

    conn.close()

    # Structure output
    extracted = {
        "model_metrics": {
            r[0]: {"resolved_rate": float(r[1]), "sem": float(r[2])}
            for r in model_metrics
        },
        "task_solve_counts": {},
        "run_results": [
            {"model": r[0], "task": r[1], "run": r[2], "resolved": bool(r[3])}
            for r in run_results
        ],
        "tasks": [
            {"id": r[0], "created_at": r[1], "repo": r[2]} for r in tasks
        ],
        "models": [
            {"name": r[0], "release_date": r[1]} for r in models
        ],
        "num_tasks": int(meta[0]),
        "num_runs_per_model": int(meta[1]),
    }

    for instance_id, model_name, successes, attempts in task_solve:
        if model_name not in extracted["task_solve_counts"]:
            extracted["task_solve_counts"][model_name] = {}
        extracted["task_solve_counts"][model_name][instance_id] = {
            "successes": int(successes),
            "attempts": int(attempts),
        }

    with open(output_path, "w") as f:
        json.dump(extracted, f)


def stage_transform(extracted_path, data_dir, output_path,
                    start_date=None, end_date=None):
    """Stage 2: Run Python transform for pass@k and contamination."""
    cmd = [
        sys.executable,
        os.path.join(SRC_DIR, "transform.py"),
        "--input", extracted_path,
        "--data-dir", data_dir,
        "--output", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Transform stage failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)


def stage_assemble(scored_path, output_path):
    """Stage 3: Run jq assembly for final JSON output."""
    jq_filter = os.path.join(SRC_DIR, "assemble.jq")
    result = subprocess.run(
        ["jq", "-f", jq_filter, scored_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"jq assembly failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    with open(output_path, "w") as f:
        f.write(result.stdout)


def main():
    parser = argparse.ArgumentParser(description="Benchmark Evaluation Pipeline")
    parser.add_argument("--data-dir", default="/app/data")
    parser.add_argument("--output", default="/app/output/leaderboard.json")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    args = parser.parse_args()

    os.makedirs("/app/intermediate", exist_ok=True)
    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    extracted = "/app/intermediate/extracted.json"
    scored = "/app/intermediate/scored.json"

    stage_extract(args.data_dir, extracted)
    stage_transform(extracted, args.data_dir, scored,
                    start_date=args.start_date, end_date=args.end_date)
    stage_assemble(scored, args.output)

    print(f"Leaderboard written to {args.output}")


if __name__ == "__main__":
    main()
