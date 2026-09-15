#!/usr/bin/env python3

"""
Solution: Fix the C library bugs, compile it, and run the full estimation pipeline.

Bug 1 (logical_error_rate): exponent uses (d-1)/2 instead of d/2+1
  - For odd d, (d-1)/2 = floor(d/2), but the formula requires floor(d/2)+1
  - Fix: change `int exponent = (d - 1) / 2;` to `int exponent = d / 2 + 1;`

Bug 2 (distillation_error_15to1): base case uses p^2 instead of p^3
  - `35.0 * p * p` should be `35.0 * p * p * p`
  - Fix: add one more `* p`

Bug 3 (Makefile): -shared-lib is invalid, should be -shared; missing -fPIC
  - Fix: add -fPIC to CFLAGS, change -shared-lib to -shared
"""

import subprocess
import ctypes
import sqlite3
import json
import math
import os


def fix_c_source():
    """Write corrected C source code."""
    c_code = r'''#include "qec_engine.h"
#include <math.h>
#include <stdlib.h>

#define A_CONSTANT 0.1

double logical_error_rate(double p, double p_th, int d) {
    double ratio = p / p_th;
    int exponent = d / 2 + 1;
    return A_CONSTANT * pow(ratio, exponent);
}

double distillation_error_15to1(double p, int k) {
    double p_T = 35.0 * p * p * p;
    for (int i = 2; i <= k; i++) {
        p_T = 35.0 * p_T * p_T * p_T;
    }
    return p_T;
}

double distillation_error_20to4(double p, int k) {
    double p_T = 56.0 * pow(p, 4);
    for (int i = 2; i <= k; i++) {
        p_T = 56.0 * pow(p_T, 4);
    }
    return p_T;
}

int find_code_distance(double p, double p_th, int n, int D, double eps_mem) {
    for (int d = 3; d <= 201; d += 2) {
        double p_L = logical_error_rate(p, p_th, d);
        if (p_L * n * D <= eps_mem) {
            return d;
        }
    }
    return -1;
}

int find_distillation_level_15to1(double p, long long T_total, double eps_dist) {
    for (int k = 1; k <= 20; k++) {
        double p_T = distillation_error_15to1(p, k);
        if (p_T * (double)T_total <= eps_dist) {
            return k;
        }
    }
    return -1;
}

int find_distillation_level_20to4(double p, long long T_total, double eps_dist) {
    for (int k = 1; k <= 20; k++) {
        double p_T = distillation_error_20to4(p, k);
        if (p_T * (double)T_total <= eps_dist) {
            return k;
        }
    }
    return -1;
}
'''
    with open("/app/src/qec_engine.c", "w") as f:
        f.write(c_code)


def fix_makefile():
    """Write corrected Makefile."""
    makefile = "CC = gcc\nCFLAGS = -Wall -O2 -fPIC\n\nlibqec.so: qec_engine.c qec_engine.h\n\t$(CC) $(CFLAGS) -shared -o $@ $< -lm\n\nclean:\n\trm -f libqec.so\n"
    with open("/app/src/Makefile", "w") as f:
        f.write(makefile)


def compile_library():
    """Compile the fixed C library."""
    subprocess.run(["make", "-C", "/app/src", "clean"], check=False,
                   capture_output=True)
    result = subprocess.run(["make", "-C", "/app/src"], check=True,
                            capture_output=True, text=True)
    print(f"Compiled: {result.stdout.strip()}")


def load_library():
    """Load compiled library and configure ctypes bindings."""
    lib = ctypes.CDLL("/app/src/libqec.so")

    lib.logical_error_rate.argtypes = [
        ctypes.c_double, ctypes.c_double, ctypes.c_int
    ]
    lib.logical_error_rate.restype = ctypes.c_double

    lib.distillation_error_15to1.argtypes = [ctypes.c_double, ctypes.c_int]
    lib.distillation_error_15to1.restype = ctypes.c_double

    lib.distillation_error_20to4.argtypes = [ctypes.c_double, ctypes.c_int]
    lib.distillation_error_20to4.restype = ctypes.c_double

    lib.find_code_distance.argtypes = [
        ctypes.c_double, ctypes.c_double,
        ctypes.c_int, ctypes.c_int, ctypes.c_double
    ]
    lib.find_code_distance.restype = ctypes.c_int

    lib.find_distillation_level_15to1.argtypes = [
        ctypes.c_double, ctypes.c_longlong, ctypes.c_double
    ]
    lib.find_distillation_level_15to1.restype = ctypes.c_int

    lib.find_distillation_level_20to4.argtypes = [
        ctypes.c_double, ctypes.c_longlong, ctypes.c_double
    ]
    lib.find_distillation_level_20to4.restype = ctypes.c_int

    return lib


def load_from_db():
    """Query hardware and algorithm parameters from SQLite database."""
    conn = sqlite3.connect("/app/hardware.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM hardware LIMIT 1")
    hw = dict(cur.fetchone())

    cur.execute("SELECT * FROM algorithms ORDER BY id")
    algs = [dict(r) for r in cur.fetchall()]

    conn.close()
    return hw, algs


def compute_total_t(alg):
    """Compute total T-gate count including rotation synthesis."""
    t_base = alg["t_count"]
    R = alg["rotation_count"]
    delta = alg["rotation_precision"]
    if R == 0 or delta <= 0:
        return t_base
    t_synth = math.ceil(3.0 * math.log2(1.0 / delta))
    return t_base + R * t_synth


def evaluate_protocol(lib, protocol, hw, alg, d, T_total, eps_dist):
    """Evaluate one distillation protocol for an algorithm.

    Derives the factory count from the throughput constraint:
    - 15-to-1: 1 T per 5kd cycles → F >= T_total * 5k / D
    - 20-to-4: 4 T per 12kd cycles → F >= T_total * 3k / D
    """
    p = hw["physical_error_rate"]
    D = alg["measurement_depth"]
    n = alg["logical_qubits"]
    t_cycle = hw["surface_code_cycle_time_us"]

    if protocol == "15-to-1":
        k = lib.find_distillation_level_15to1(p, T_total, eps_dist)
        if k < 0:
            return None
        F = max(1, math.ceil(T_total * 5 * k / D))
        fac_qubits_each = 8 * k * d * d
    else:  # 20-to-4
        k = lib.find_distillation_level_20to4(p, T_total, eps_dist)
        if k < 0:
            return None
        F = max(1, math.ceil(T_total * 3 * k / D))
        fac_qubits_each = 20 * k * d * d

    q_data = math.ceil(1.5 * n) * 2 * d * d
    q_factories = F * fac_qubits_each
    q_total = q_data + q_factories
    t_us = D * d * t_cycle
    V = q_total * t_us

    return {
        "optimal_protocol": protocol,
        "distillation_level": int(k),
        "code_distance": int(d),
        "total_t_count": int(T_total),
        "num_factories": int(F),
        "data_qubits": int(q_data),
        "factory_qubits": int(q_factories),
        "total_physical_qubits": int(q_total),
        "execution_time_us": float(t_us),
        "spacetime_volume": float(V),
    }


def main():
    # Step 1: Fix and compile the C library
    fix_c_source()
    fix_makefile()
    compile_library()
    lib = load_library()

    # Step 2: Load parameters from database
    hw, algs = load_from_db()

    print(f"Hardware: p={hw['physical_error_rate']}, "
          f"p_th={hw['threshold_error_rate']}, "
          f"t_cycle={hw['surface_code_cycle_time_us']}us")

    # Step 3: Estimate resources for each algorithm
    results = []
    for alg in algs:
        epsilon = alg["target_error"]
        eps_mem = epsilon / 3.0
        eps_dist = epsilon / 3.0

        T_total = compute_total_t(alg)
        d = lib.find_code_distance(
            hw["physical_error_rate"], hw["threshold_error_rate"],
            alg["logical_qubits"], alg["measurement_depth"], eps_mem
        )
        assert d > 0, f"No valid code distance for {alg['name']}"

        # Evaluate both protocols
        res_a = evaluate_protocol(lib, "15-to-1", hw, alg, d, T_total, eps_dist)
        res_b = evaluate_protocol(lib, "20-to-4", hw, alg, d, T_total, eps_dist)

        # Select optimal
        if res_a is None and res_b is None:
            raise ValueError(f"No feasible protocol for {alg['name']}")
        elif res_a is None:
            best = res_b
        elif res_b is None:
            best = res_a
        elif res_a["total_physical_qubits"] <= res_b["total_physical_qubits"]:
            best = res_a
        else:
            best = res_b

        best["name"] = alg["name"]
        results.append(best)

        print(f"  {alg['name']}: protocol={best['optimal_protocol']}, "
              f"d={d}, k={best['distillation_level']}, "
              f"F={best['num_factories']}, "
              f"q_total={best['total_physical_qubits']:,}")

    # Step 4: Write output
    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to /app/output/results.json")


if __name__ == "__main__":
    main()
