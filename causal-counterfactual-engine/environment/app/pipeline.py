#!/usr/bin/env python3
"""Causal inference benchmarking pipeline using causal-profiler."""

import os
import json
import yaml
import sqlite3
import random
import subprocess
from datetime import datetime
import numpy as np
import torch

from causal_profiler import Profiler, SpaceConfig, ErrorMetric


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"Object of type {type(o)} is not JSON serializable")


def main():
    with open("/app/spaces_config.yaml") as f:
        config = yaml.safe_load(f)

    os.makedirs("/app/output/graphs", exist_ok=True)

    conn = sqlite3.connect("/app/output/benchmarks.db")
    with open("/app/schema.sql") as f:
        conn.executescript(f.read())

    report_spaces = []

    for space_cfg in config["spaces"]:
        space_name = space_cfg.pop("name")
        seed = space_cfg.pop("seed", 42)
        set_seed(seed)

        # Create space of interest from YAML config
        space = SpaceConfig(**space_cfg)
        profiler = Profiler(space)

        # Generate benchmark data
        data, queries, graph = profiler.run()

        # Get query results
        targets = [q.ground_truth for q in queries]
        user_estimates = [0.0] * len(targets)

        error = profiler.compute_error(user_estimates, targets)

        # Store in database
        conn.execute(
            "INSERT INTO results (space, error, queries) VALUES (?, ?, ?)",
            (space_name, error, len(queries))
        )

        report_spaces.append({
            "name": space_name,
            "error": error,
            "num_queries": len(queries),
        })

    conn.commit()
    conn.close()

    with open("/app/output/report.json", "w") as f:
        json.dump({"spaces": report_spaces}, f, indent=2, default=json_default)

    with open("/app/output/.completed", "w") as f:
        f.write("done")

    print(f"Pipeline completed: {len(report_spaces)} spaces evaluated")


if __name__ == "__main__":
    main()
