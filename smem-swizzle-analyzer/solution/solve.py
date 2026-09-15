#!/usr/bin/env python3
"""Fix all bugs and implement missing modules in the smem_optimizer project."""

import os

# -------------------------------------------------------------------
# 1. Fix CMakeLists.txt: change library type from STATIC to SHARED
# -------------------------------------------------------------------
cmake_path = "/app/CMakeLists.txt"
with open(cmake_path, "r") as f:
    cmake_content = f.read()
cmake_content = cmake_content.replace(
    "add_library(smembank src/smem_bank.c)",
    "add_library(smembank SHARED src/smem_bank.c)",
)
with open(cmake_path, "w") as f:
    f.write(cmake_content)

# -------------------------------------------------------------------
# 2. Fix smem_bank.c: change metric from sum-of-excess to max-per-bank
# -------------------------------------------------------------------
with open("/app/src/smem_bank.c", "w") as f:
    f.write("""\
#include "smem_bank.h"

int compute_bank_id(int byte_address) {
    return (byte_address / BANK_WIDTH_BYTES) % NUM_BANKS;
}

int count_bank_conflicts(const int *byte_addresses, size_t count) {
    if (count == 0) return 0;

    int bank_counts[NUM_BANKS];
    for (int i = 0; i < NUM_BANKS; i++) bank_counts[i] = 0;

    for (size_t i = 0; i < count; i++) {
        int bank = compute_bank_id(byte_addresses[i]);
        bank_counts[bank]++;
    }

    /* Maximum threads accessing any single bank = serialization rounds */
    int max_count = 0;
    for (int b = 0; b < NUM_BANKS; b++) {
        if (bank_counts[b] > max_count) {
            max_count = bank_counts[b];
        }
    }
    return max_count > 0 ? max_count : 1;
}
""")

# -------------------------------------------------------------------
# 3. Implement swizzle.py
# -------------------------------------------------------------------
with open("/app/smem_optimizer/swizzle.py", "w") as f:
    f.write('''\
"""XOR-based shared memory index swizzling."""


def apply_swizzle(y, x, NX, sizeof_T=4, sizeof_TC=4):
    elems_per_chunk = sizeof_TC // sizeof_T
    x_chunk = x * sizeof_T // sizeof_TC
    y_chunk = y
    x_chunk_swz = y_chunk ^ x_chunk
    if elems_per_chunk > 1:
        x_swz = (x_chunk_swz * elems_per_chunk) % NX + x % elems_per_chunk
    else:
        x_swz = x_chunk_swz % NX
    return x_swz


def verify_bijective(NX, NY, sizeof_T=4, sizeof_TC=4):
    for y in range(NY):
        seen = set()
        for x in range(NX):
            xs = apply_swizzle(y, x, NX, sizeof_T, sizeof_TC)
            if xs < 0 or xs >= NX or xs in seen:
                return False
            seen.add(xs)
    return True
''')

# -------------------------------------------------------------------
# 4. Implement padding.py
# -------------------------------------------------------------------
with open("/app/smem_optimizer/padding.py", "w") as f:
    f.write('''\
"""Padding-based bank conflict avoidance."""

from smem_optimizer.banking import count_bank_conflicts

DTYPE_SIZES = {"float32": 4, "float64": 8, "float16": 2}


def find_optimal_padding(NX, NY, sizeof_T, vectorize_width, access):
    if access == "row":
        addrs = [(t % NX) * sizeof_T for t in range(32)]
        baseline = count_bank_conflicts(addrs)
        return (0, baseline, 0)

    addrs_base = [(t % NY * NX) * sizeof_T for t in range(32)]
    baseline = count_bank_conflicts(addrs_base)

    best_pad = 0
    best_conflict = baseline

    for pad in range(1, max(NX, 32) + 1):
        nx_pad = NX + pad
        if vectorize_width > 1 and nx_pad % vectorize_width != 0:
            continue
        addrs = [(t % NY * nx_pad) * sizeof_T for t in range(32)]
        c = count_bank_conflicts(addrs)
        if c < best_conflict:
            best_conflict = c
            best_pad = pad
            if c == 1:
                break
    overhead = best_pad * NY * sizeof_T
    return (best_pad, best_conflict, overhead)
''')

# -------------------------------------------------------------------
# 5. Implement evaluator.py
# -------------------------------------------------------------------
with open("/app/smem_optimizer/evaluator.py", "w") as f:
    f.write('''\
"""Shared memory layout optimizer: evaluates strategies for GEMM tiling."""

import csv
import json
import yaml
from functools import partial

from smem_optimizer.banking import count_bank_conflicts
from smem_optimizer.swizzle import apply_swizzle, verify_bijective
from smem_optimizer.padding import find_optimal_padding

DTYPE_SIZES = {"float32": 4, "float64": 8, "float16": 2}


def load_configs(yaml_path):
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    return data["kernels"]


def next_power_of_2(n):
    if n <= 1:
        return 1
    n -= 1
    n |= n >> 1
    n |= n >> 2
    n |= n >> 4
    n |= n >> 8
    n |= n >> 16
    return n + 1


def compute_sizeof_tc(sizeof_T, vectorize_width):
    min_tc = max(sizeof_T, vectorize_width * sizeof_T)
    return next_power_of_2(min_tc)


def evaluate_config(config):
    name = config["name"]
    NX = config["NX"]
    NY = config["NY"]
    sizeof_T = DTYPE_SIZES[config["dtype"]]
    access = config["access"]
    vec_w = config["vectorize_width"]

    # Baseline
    if access == "column":
        base_addrs = [(t % NY * NX) * sizeof_T for t in range(32)]
    else:
        base_addrs = [(t % NX) * sizeof_T for t in range(32)]
    baseline = count_bank_conflicts(base_addrs)

    # XOR swizzle
    stc = compute_sizeof_tc(sizeof_T, vec_w)
    swz_fn = partial(apply_swizzle, NX=NX, sizeof_T=sizeof_T, sizeof_TC=stc)
    if access == "column":
        swz_addrs = []
        for t in range(32):
            row = t % NY
            col_swz = swz_fn(row, 0)
            swz_addrs.append((row * NX + col_swz) * sizeof_T)
    else:
        swz_addrs = []
        for t in range(32):
            col = t % NX
            col_swz = swz_fn(0, col)
            swz_addrs.append(col_swz * sizeof_T)
    swz_conflict = count_bank_conflicts(swz_addrs)

    # Padding
    pad_amount, pad_conflict, pad_overhead = find_optimal_padding(
        NX, NY, sizeof_T, vec_w, access
    )

    return {
        "name": name,
        "baseline_conflicts": baseline,
        "swizzle_conflicts": swz_conflict,
        "swizzle_sizeof_tc": stc,
        "padding_conflicts": pad_conflict,
        "padding_amount": pad_amount,
        "padding_overhead_bytes": pad_overhead,
    }


def select_optimal(evaluation):
    baseline = evaluation["baseline_conflicts"]
    swz = evaluation["swizzle_conflicts"]
    pad = evaluation["padding_conflicts"]

    if baseline == 1:
        return {"optimal_strategy": "none", "optimal_conflicts": 1}

    if pad < swz:
        return {"optimal_strategy": "padding", "optimal_conflicts": pad}
    else:
        return {"optimal_strategy": "swizzle", "optimal_conflicts": swz}


def write_json_report(results, path):
    with open(path, "w") as f:
        json.dump(results, f, indent=2)


CSV_COLUMNS = [
    "name", "baseline_conflicts", "swizzle_sizeof_tc", "swizzle_conflicts",
    "padding_amount", "padding_conflicts", "padding_overhead_bytes",
    "optimal_strategy", "optimal_conflicts",
]


def write_csv_report(results, path):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            writer.writerow(r)
''')

print("All fixes applied successfully.")
