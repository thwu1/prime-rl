#!/usr/bin/env python3
"""Generate deterministic benchmark run data for COCO-style performance analysis.

Produces synthetic but realistic function-evaluation data for three optimization
algorithms on a subset of BBOB functions across multiple dimensions and instances.
"""
import json
import os


def string_hash(s):
    """Deterministic hash (djb2 variant)."""
    h = 5381
    for c in s:
        h = ((h * 33) + ord(c)) & 0xFFFFFFFF
    return h


class LCG:
    """Linear congruential generator for reproducible pseudo-random floats."""
    def __init__(self, seed):
        self.state = seed & 0xFFFFFFFF

    def next_float(self):
        self.state = (self.state * 1103515245 + 12345) & 0x7FFFFFFF
        return self.state / 0x7FFFFFFF


ALGORITHMS = ["CMAES", "DiffEvolution", "NelderMead"]
FUNCTIONS = [1, 8, 10, 15, 21]
DIMENSIONS = [5, 10, 20, 40]
INSTANCES = list(range(1, 6))
TARGET_STRS = ["10.0", "1.0", "0.01", "0.0001", "1e-08"]

FUNCTION_GROUPS = {
    "separable": [1],
    "moderate_conditioning": [8],
    "high_conditioning": [10],
    "multimodal_global": [15],
    "multimodal_weak": [21],
}

# Base evaluation counts at dimension 5 for each target
# [target 10.0, 1.0, 0.01, 0.0001, 1e-08]
BASE = {
    ("CMAES", 1):  [75, 150, 290, 470, 700],
    ("CMAES", 8):  [250, 600, 1250, 2500, 5000],
    ("CMAES", 10): [200, 500, 1500, 3500, 7500],
    ("CMAES", 15): [400, 1000, 2500, 7500, 20000],
    ("CMAES", 21): [500, 1500, 4000, 10000, 25000],

    ("DiffEvolution", 1):  [100, 400, 1000, 2500, 6000],
    ("DiffEvolution", 8):  [200, 750, 2500, 7500, 20000],
    ("DiffEvolution", 10): [500, 2500, 10000, 30000, 75000],
    ("DiffEvolution", 15): [300, 750, 3000, 10000, 25000],
    ("DiffEvolution", 21): [400, 1000, 5000, 20000, 50000],

    ("NelderMead", 1):  [50, 125, 400, 1000, 2500],
    ("NelderMead", 8):  [150, 500, 2000, 10000, 30000],
    ("NelderMead", 10): [300, 1000, 4000, 15000, 40000],
    ("NelderMead", 15): [500, 2500, 10000, 40000, 100000],
    ("NelderMead", 21): [750, 3000, 15000, 50000, 125000],
}

# Dimension scaling exponents: evals ~ dim^exponent
EXPONENTS = {
    ("CMAES", 1):  1.0,
    ("CMAES", 8):  1.15,
    ("CMAES", 10): 1.05,
    ("CMAES", 15): 1.25,
    ("CMAES", 21): 1.35,

    ("DiffEvolution", 1):  1.3,
    ("DiffEvolution", 8):  1.5,
    ("DiffEvolution", 10): 1.8,
    ("DiffEvolution", 15): 1.2,
    ("DiffEvolution", 21): 1.45,

    ("NelderMead", 1):  1.5,
    ("NelderMead", 8):  1.8,
    ("NelderMead", 10): 1.6,
    ("NelderMead", 15): 2.0,
    ("NelderMead", 21): 1.9,
}


def budget(dim):
    return 10000 * dim


def generate_run(algo, func, dim, inst):
    b = budget(dim)
    base = BASE[(algo, func)]
    exp = EXPONENTS[(algo, func)]
    rng = LCG(string_hash(f"{algo}_{func}_{dim}_{inst}"))

    targets_reached = {}
    prev = 0
    for i in range(len(TARGET_STRS)):
        scaled = base[i] * (dim / 5.0) ** exp
        noise = 1.0 + 0.3 * (rng.next_float() - 0.5)
        evals = int(round(scaled * noise))
        evals = max(evals, prev + 10)
        if evals > b:
            break
        targets_reached[TARGET_STRS[i]] = evals
        prev = evals

    return {
        "function_id": func,
        "dimension": dim,
        "instance": inst,
        "budget": b,
        "targets_reached": targets_reached,
    }


def main():
    os.makedirs("/app/data", exist_ok=True)

    for algo in ALGORITHMS:
        runs = []
        for func in FUNCTIONS:
            for dim in DIMENSIONS:
                for inst in INSTANCES:
                    runs.append(generate_run(algo, func, dim, inst))
        with open(f"/app/data/{algo}.json", "w") as f:
            json.dump({"algorithm": algo, "runs": runs}, f, indent=2)

    meta = {
        "algorithms": ALGORITHMS,
        "functions": FUNCTIONS,
        "dimensions": DIMENSIONS,
        "instances": list(range(1, 6)),
        "targets": TARGET_STRS,
        "function_groups": FUNCTION_GROUPS,
        "budget_formula": "10000 * dimension",
    }
    with open("/app/data/metadata.json", "w") as f:
        json.dump(meta, f, indent=2)


if __name__ == "__main__":
    main()
