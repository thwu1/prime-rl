#!/usr/bin/env python3
"""Run the dynamic optimizer on all configured GMPB instances."""

import json
import sqlite3
import sys
sys.path.insert(0, "/app")

from gmpb import GMPB
from optimizer import DynamicOptimizer

with open("/app/config.json") as f:
    config = json.load(f)

# Set up SQLite database
conn = sqlite3.connect("/app/results.db")
conn.execute("""CREATE TABLE IF NOT EXISTS runs (
    instance_name TEXT PRIMARY KEY,
    dim INTEGER,
    num_peaks INTEGER,
    shift_severity REAL,
    change_frequency INTEGER,
    num_environments INTEGER,
    seed INTEGER,
    offline_error REAL,
    threshold REAL,
    passed INTEGER
)""")
conn.execute("""CREATE TABLE IF NOT EXISTS env_stats (
    instance_name TEXT,
    env_index INTEGER,
    avg_error REAL,
    best_found REAL,
    optimum_value REAL,
    PRIMARY KEY (instance_name, env_index)
)""")
conn.commit()

results = {}
for inst_name, inst_cfg in config["instances"].items():
    benchmark = GMPB(
        dim=inst_cfg["dim"],
        num_peaks=inst_cfg["num_peaks"],
        shift_severity=inst_cfg["shift_severity"],
        change_frequency=inst_cfg["change_frequency"],
        num_environments=inst_cfg["num_environments"],
        seed=inst_cfg["seed"],
    )
    optimizer = DynamicOptimizer(benchmark, seed=42)
    result = optimizer.run()
    results[inst_name] = result
    threshold = inst_cfg["offline_error_threshold"]
    passed = 1 if result["offline_error"] < threshold else 0
    status = "PASS" if passed else "FAIL"
    print(
        f"{inst_name}: offline_error={result['offline_error']:.4f}  "
        f"threshold={threshold}  [{status}]"
    )

    conn.execute(
        "INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (inst_name, inst_cfg["dim"], inst_cfg["num_peaks"],
         inst_cfg["shift_severity"], inst_cfg["change_frequency"],
         inst_cfg["num_environments"], inst_cfg["seed"],
         result["offline_error"], threshold, passed)
    )

    for es in benchmark.get_env_stats():
        conn.execute(
            "INSERT OR REPLACE INTO env_stats VALUES (?, ?, ?, ?, ?)",
            (inst_name, es["env_index"], es["avg_error"],
             es["best_found"], es["optimum_value"])
        )

    conn.commit()

conn.close()

with open("/app/results.json", "w") as f:
    json.dump(results, f, indent=2)

print(f"\nResults written to /app/results.json and /app/results.db")
