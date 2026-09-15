#!/usr/bin/env python3
"""Evaluation runner for the Moving Peaks Benchmark.

Loads the C benchmark library (libgmpb.so) via ctypes and reads instance
configurations from the SQLite database (config.db).

Run: python3 /app/runner.py
"""


import ctypes
import sqlite3
import sys
import json
import importlib.util
import os

LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libgmpb.so")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.db")


def load_library(path=None):
    """Load and configure libgmpb.so via ctypes."""
    lib = ctypes.CDLL(path or LIB_PATH)

    lib.gmpb_create.argtypes = [
        ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_double, ctypes.c_int, ctypes.c_uint64,
    ]
    lib.gmpb_create.restype = ctypes.c_void_p

    lib.gmpb_destroy.argtypes = [ctypes.c_void_p]
    lib.gmpb_destroy.restype = None

    lib.gmpb_evaluate.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_double),
    ]
    lib.gmpb_evaluate.restype = ctypes.c_double

    lib.gmpb_get_optimum.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_double),
    ]
    lib.gmpb_get_optimum.restype = ctypes.c_double

    lib.gmpb_trigger_change.argtypes = [ctypes.c_void_p]
    lib.gmpb_trigger_change.restype = None

    lib.gmpb_change_frequency.argtypes = [ctypes.c_void_p]
    lib.gmpb_change_frequency.restype = ctypes.c_int

    lib.gmpb_dimension.argtypes = [ctypes.c_void_p]
    lib.gmpb_dimension.restype = ctypes.c_int

    lib.gmpb_num_environments.argtypes = [ctypes.c_void_p]
    lib.gmpb_num_environments.restype = ctypes.c_int

    lib.gmpb_num_peaks.argtypes = [ctypes.c_void_p]
    lib.gmpb_num_peaks.restype = ctypes.c_int

    return lib


def load_instances(db_path=None):
    """Load instance configurations and thresholds from SQLite."""
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row

    instances = {}
    for row in conn.execute("SELECT * FROM instances ORDER BY name"):
        instances[row["name"]] = dict(row)

    thresholds = {}
    for row in conn.execute("SELECT * FROM thresholds ORDER BY name"):
        thresholds[row["name"]] = row["max_offline_error"]

    conn.close()
    return instances, thresholds


def run_instance(lib, instance_name, instance_cfg, optimizer_class,
                 optimizer_seed=42):
    """Run one problem instance and return the offline error."""
    ctx = lib.gmpb_create(
        instance_cfg["num_peaks"],
        instance_cfg["dimension"],
        instance_cfg["change_frequency"],
        instance_cfg["shift_severity"],
        instance_cfg["num_environments"],
        instance_cfg["seed"],
    )
    if not ctx:
        raise RuntimeError(f"gmpb_create failed for {instance_name}")

    dim = instance_cfg["dimension"]
    try:
        optimizer = optimizer_class(
            dimension=dim,
            bounds=(0.0, 100.0),
            num_peaks=instance_cfg["num_peaks"],
            seed=optimizer_seed,
        )

        cumulative_error = 0.0
        total_evals = 0

        for env_idx in range(instance_cfg["num_environments"]):
            if env_idx > 0:
                lib.gmpb_trigger_change(ctx)

            best_so_far = float("-inf")
            env_evals = 0
            first_tell = True

            while env_evals < instance_cfg["change_frequency"]:
                solutions = optimizer.ask()
                values = []
                for s in solutions:
                    arr = (ctypes.c_double * dim)(*s)
                    val = lib.gmpb_evaluate(ctx, arr)
                    values.append(val)

                opt_pos = (ctypes.c_double * dim)()
                optimum_value = lib.gmpb_get_optimum(ctx, opt_pos)

                for v in values:
                    if v > best_so_far:
                        best_so_far = v
                    error = max(0.0, optimum_value - best_so_far)
                    cumulative_error += error
                    total_evals += 1
                    env_evals += 1

                notify_change = (env_idx > 0) and first_tell
                optimizer.tell(solutions, values, notify_change)
                first_tell = False

        return cumulative_error / total_evals
    finally:
        lib.gmpb_destroy(ctx)


def main():
    lib = load_library()
    instances, thresholds = load_instances()

    spec = importlib.util.spec_from_file_location("optimizer", "/app/optimizer.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    optimizer_class = mod.Optimizer

    results = {}
    all_passed = True
    for name in sorted(instances):
        cfg = instances[name]
        error = run_instance(lib, name, cfg, optimizer_class)
        threshold = thresholds[name]
        passed = error < threshold
        if not passed:
            all_passed = False
        results[name] = dict(offline_error=round(error, 4),
                             threshold=threshold, passed=passed)
        tag = "PASS" if passed else "FAIL"
        print(f"{name}: offline_error={error:.4f}  threshold={threshold}  [{tag}]")

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nOverall: {'PASS' if all_passed else 'FAIL'}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
