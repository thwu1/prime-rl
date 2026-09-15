#!/usr/bin/env python3
"""Build /app/benchmark.db from raw data files during Docker image build."""

import json
import os
import sqlite3

DATA_DIR = "/tmp/build_data"
DB_PATH = "/app/benchmark.db"


def main():
    os.makedirs("/app", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # -- Schema --
    c.execute("""
        CREATE TABLE crash_reports (
            report_id TEXT PRIMARY KEY,
            raw_text TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE vm_test_runs (
            case_id TEXT,
            bug_id TEXT,
            patch_id TEXT,
            vm_index INTEGER,
            outcome TEXT,
            PRIMARY KEY (case_id, vm_index)
        )
    """)

    c.execute("""
        CREATE TABLE experiment_configs (
            config_name TEXT PRIMARY KEY,
            cost_per_bug REAL
        )
    """)

    c.execute("""
        CREATE TABLE experiment_results (
            config_name TEXT,
            bug_id TEXT,
            verdict TEXT,
            build_status TEXT,
            PRIMARY KEY (config_name, bug_id),
            FOREIGN KEY (config_name) REFERENCES experiment_configs(config_name)
        )
    """)

    c.execute("""
        CREATE TABLE experiment_bugs (
            bug_id TEXT PRIMARY KEY
        )
    """)

    c.execute("""
        CREATE TABLE shadow_byte_legend (
            byte_value TEXT PRIMARY KEY,
            description TEXT NOT NULL
        )
    """)

    # -- Populate crash reports --
    reports_dir = os.path.join(DATA_DIR, "reports")
    for fname in sorted(os.listdir(reports_dir)):
        if fname.endswith(".txt"):
            report_id = os.path.splitext(fname)[0]
            with open(os.path.join(reports_dir, fname)) as f:
                raw_text = f.read()
            c.execute("INSERT INTO crash_reports VALUES (?, ?)",
                      (report_id, raw_text))

    # -- Populate VM test runs --
    with open(os.path.join(DATA_DIR, "vm_results.json")) as f:
        vm_data = json.load(f)
    for case_id, case in vm_data.items():
        for idx, outcome in enumerate(case["vm_results"]):
            c.execute("INSERT INTO vm_test_runs VALUES (?, ?, ?, ?, ?)",
                      (case_id, case["bug_id"], case["patch_id"], idx, outcome))

    # -- Populate experiment data --
    with open(os.path.join(DATA_DIR, "experiment.json")) as f:
        exp_data = json.load(f)

    for bug_id in exp_data["bugs"]:
        c.execute("INSERT INTO experiment_bugs VALUES (?)", (bug_id,))

    for config_name, config in exp_data["configs"].items():
        c.execute("INSERT INTO experiment_configs VALUES (?, ?)",
                  (config_name, config["cost_per_bug"]))
        for bug_id, result in config["results"].items():
            c.execute("INSERT INTO experiment_results VALUES (?, ?, ?, ?)",
                      (config_name, bug_id,
                       result["verdict"], result["build_status"]))

    # -- Populate KASAN shadow byte legend --
    legend = {
        "00": "Addressable",
        "01": "Partially accessible: 1 of 8 bytes",
        "02": "Partially accessible: 2 of 8 bytes",
        "03": "Partially accessible: 3 of 8 bytes",
        "04": "Partially accessible: 4 of 8 bytes",
        "05": "Partially accessible: 5 of 8 bytes",
        "06": "Partially accessible: 6 of 8 bytes",
        "07": "Partially accessible: 7 of 8 bytes",
        "f1": "Stack left redzone",
        "f2": "Stack mid redzone",
        "f3": "Stack right redzone",
        "f5": "Stack use-after-return",
        "f8": "Stack use-after-scope",
        "f9": "Global redzone",
        "fa": "Slab left redzone",
        "fb": "Object free padding",
        "fc": "Slab redzone",
        "fd": "Freed slab object",
        "fe": "Pool/page freed",
        "ff": "Page not allocated",
    }
    for byte_val, desc in legend.items():
        c.execute("INSERT INTO shadow_byte_legend VALUES (?, ?)",
                  (byte_val, desc))

    conn.commit()
    conn.close()
    print(f"Database created at {DB_PATH}")


if __name__ == "__main__":
    main()
