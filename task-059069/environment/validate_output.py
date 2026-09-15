#!/usr/bin/env python3
"""Eurobench PI output format validator.

Validates that gait stability PI output files conform to the protocol
specification stored in the SQLite configuration database. Checks structural
compliance only - does not validate numerical correctness of computed metrics.

Usage: validate_output.py <input_dir> <output_dir>
"""

import os
import re
import sqlite3
import sys

import yaml

DB_PATH = '/app/protocol/config.db'


def get_required_metrics(db_path):
    """Read required metrics from protocol database."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    spatiotemporal_keys = []
    stability_keys = []

    c.execute("SELECT metric_name, output_type FROM required_metrics")
    for name, otype in c.fetchall():
        if otype == 'spatiotemporal':
            spatiotemporal_keys.append(name)
        elif otype == 'stability':
            stability_keys.append(name)

    c.execute("SELECT column_name FROM summary_columns ORDER BY column_order")
    summary_columns = [row[0] for row in c.fetchall()]

    conn.close()
    return spatiotemporal_keys, stability_keys, summary_columns


def discover_runs(input_dir):
    """Discover subject/condition/run combinations from input HDF5 files."""
    runs = []
    pattern = re.compile(r"subject_(\d+)_cond_(\d+)_run_(\d+)\.h5")
    for fn in os.listdir(input_dir):
        m = pattern.match(fn)
        if m:
            runs.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    return sorted(runs)


def check_metric_schema(data, key, errors, filepath):
    """Check that a metric entry contains mean, std, and unit fields."""
    if key not in data:
        errors.append(f"{filepath}: missing required metric '{key}'")
        return
    entry = data[key]
    if not isinstance(entry, dict):
        errors.append(
            f"{filepath}: metric '{key}' must be a dict, got {type(entry).__name__}"
        )
        return
    for field in ["mean", "std", "unit"]:
        if field not in entry:
            errors.append(f"{filepath}: metric '{key}' missing '{field}' field")


def validate(input_dir, output_dir):
    errors = []

    # Read requirements from protocol database
    if not os.path.exists(DB_PATH):
        errors.append(f"Protocol database not found: {DB_PATH}")
        return errors

    spatiotemporal_keys, stability_keys, summary_columns = \
        get_required_metrics(DB_PATH)

    runs = discover_runs(input_dir)
    if not runs:
        errors.append(f"No HDF5 runs discovered in {input_dir}")
        return errors

    conditions = {}
    for sid, cid, rid in runs:
        conditions.setdefault((sid, cid), []).append(rid)

    # --- Per-run output files ---
    for sid, cid, rid in runs:
        pfx = f"subject_{sid:02d}_cond_{cid:02d}_run_{rid:02d}"

        sp_file = f"{pfx}_spatiotemporal.yaml"
        sp_path = os.path.join(output_dir, sp_file)
        if not os.path.exists(sp_path):
            errors.append(f"Missing: {sp_file}")
        else:
            with open(sp_path) as f:
                data = yaml.safe_load(f)
            if data is None:
                errors.append(f"{sp_file}: empty or invalid YAML")
            else:
                for key in spatiotemporal_keys:
                    check_metric_schema(data, key, errors, sp_file)

        st_file = f"{pfx}_stability.yaml"
        st_path = os.path.join(output_dir, st_file)
        if not os.path.exists(st_path):
            errors.append(f"Missing: {st_file}")
        else:
            with open(st_path) as f:
                data = yaml.safe_load(f)
            if data is None:
                errors.append(f"{st_file}: empty or invalid YAML")
            else:
                for key in stability_keys:
                    check_metric_schema(data, key, errors, st_file)
                if not any("xcom" in k.lower() for k in data.keys()):
                    errors.append(
                        f"{st_file}: must contain at least one field "
                        f"with 'xcom' in its name"
                    )

    # --- Per-condition aggregated files ---
    for (sid, cid), rids in conditions.items():
        agg_file = f"subject_{sid:02d}_cond_{cid:02d}_aggregated.yaml"
        agg_path = os.path.join(output_dir, agg_file)
        if not os.path.exists(agg_path):
            errors.append(f"Missing: {agg_file}")
        else:
            with open(agg_path) as f:
                data = yaml.safe_load(f)
            if data is None:
                errors.append(f"{agg_file}: empty or invalid YAML")
            else:
                found_metric = False
                for key in spatiotemporal_keys + stability_keys:
                    if key in data:
                        found_metric = True
                        check_metric_schema(data, key, errors, agg_file)
                if not found_metric:
                    errors.append(f"{agg_file}: no recognized metrics found")

    # --- Summary CSV ---
    summary_path = os.path.join(output_dir, "summary.csv")
    if not os.path.exists(summary_path):
        errors.append("Missing: summary.csv")
    else:
        with open(summary_path) as f:
            lines = f.readlines()
        if len(lines) < 2:
            errors.append("summary.csv: must have header + at least one data row")
        else:
            header = lines[0].strip().lower()
            for col in summary_columns:
                if col not in header:
                    errors.append(
                        f"summary.csv: missing required column '{col}'"
                    )
            expected_rows = len(runs)
            actual_rows = len(lines) - 1
            if actual_rows < expected_rows:
                errors.append(
                    f"summary.csv: expected >= {expected_rows} data rows, "
                    f"got {actual_rows}"
                )

    return errors


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input_dir> <output_dir>", file=sys.stderr)
        sys.exit(2)

    input_dir, output_dir = sys.argv[1], sys.argv[2]

    if not os.path.isdir(input_dir):
        print(f"Error: input directory not found: {input_dir}", file=sys.stderr)
        sys.exit(2)
    if not os.path.isdir(output_dir):
        print(f"Error: output directory not found: {output_dir}", file=sys.stderr)
        sys.exit(2)

    errors = validate(input_dir, output_dir)

    if errors:
        print(f"VALIDATION FAILED - {len(errors)} error(s):")
        for e in errors:
            print(f"  ERROR: {e}")
        sys.exit(1)
    else:
        print("VALIDATION PASSED - all output files conform to protocol specification.")
        sys.exit(0)


if __name__ == "__main__":
    main()
