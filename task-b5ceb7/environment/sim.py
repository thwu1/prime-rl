#!/usr/bin/env python3
"""GPU shared memory bank conflict simulator.

Reads GPU architecture parameters from gpu_config.json and kernel access
patterns from kernels.json. Computes bank conflict metrics (wavefronts,
total_conflicts, conflict_free) for each kernel and writes results to
sim_output.json.

Bank conflict model:
  - Shared memory is divided into num_banks equally-sized banks.
  - Each bank is bank_width_bytes wide.
  - Bank index for a byte address: floor(addr / bank_width_bytes) % num_banks
  - The broadcast rule: multiple threads reading the exact same address do
    not conflict (hardware serves via broadcast).
  - Wavefronts = max across all banks of (distinct addresses per bank).
  - Per-bank conflicts = max(0, distinct_addresses - 1).
  - Total conflicts = sum of per-bank conflicts.
  - Conflict-free iff wavefronts <= 1.
"""

import json
import sys


def load_config(path):
    with open(path) as f:
        return json.load(f)


def compute_bank(addr, config):
    """Map a byte address to its bank index."""
    return (addr // config["bank_width_bytes"]) % config["num_banks"]


def evaluate_formula(formula, warp_size):
    """Evaluate a Python expression for each thread index t in [0, warp_size)."""
    offsets = []
    for t in range(warp_size):
        offsets.append(int(eval(formula, {"__builtins__": {}}, {"t": t})))
    return offsets


def analyze_pattern(offsets, config):
    """Analyze bank conflicts for a set of byte offsets.

    Groups offsets by bank, deduplicates via sets (broadcast rule),
    then computes wavefronts and conflict counts.
    """
    bank_to_addrs = {}
    for offset in offsets:
        bank = compute_bank(offset, config)
        if bank not in bank_to_addrs:
            bank_to_addrs[bank] = set()
        bank_to_addrs[bank].add(offset)

    # Compute wavefronts and conflicts across all banks
    wavefronts = 0
    total_conflicts = 0
    for bank_id in range(config["num_banks"]):
        distinct = len(bank_to_addrs.get(bank_id, set()))
        wavefronts += distinct  # accumulate wavefront contributions
        if distinct > 1:
            total_conflicts += distinct - 1

    if wavefronts == 0 and len(offsets) > 0:
        wavefronts = 1

    conflict_free = total_conflicts == 0

    return {
        "wavefronts": wavefronts,
        "total_conflicts": total_conflicts,
        "conflict_free": conflict_free,
    }


def main():
    config = load_config("/app/gpu_config.json")

    with open("/app/kernels.json") as f:
        kernels_data = json.load(f)

    results = {}
    for name, kernel in kernels_data["kernels"].items():
        if "access_explicit" in kernel:
            offsets = list(kernel["access_explicit"])
            if len(offsets) != config["warp_size"]:
                print(
                    f"Warning: {name} has {len(offsets)} offsets, "
                    f"expected {config['warp_size']}",
                    file=sys.stderr,
                )
        else:
            offsets = evaluate_formula(
                kernel["access_formula"], config["warp_size"]
            )

        results[name] = analyze_pattern(offsets, config)

    with open("/app/sim_output.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Simulation complete. Results written to /app/sim_output.json")
    for name, r in sorted(results.items()):
        status = "conflict-free" if r["conflict_free"] else "CONFLICTS"
        print(
            f"  {name}: wavefronts={r['wavefronts']}, "
            f"conflicts={r['total_conflicts']}, {status}"
        )


if __name__ == "__main__":
    main()
