#!/usr/bin/env python3
"""Solution for GPU Shared Memory Profiling Pipeline Debug.

Fixes three bugs:
1. gpu_config.json: num_banks should be 32 (was 16)
2. sim.py: wavefronts should use max, not sum
3. kernels.json: stride_7 formula should be t * 28 (was t * 24)

Then computes corrected metrics and optimization analysis.
"""


import json

NUM_BANKS = 32
BANK_WIDTH = 4
WARP_SIZE = 32


def compute_bank(addr):
    return (addr // BANK_WIDTH) % NUM_BANKS


def evaluate_formula(formula):
    offsets = []
    for t in range(WARP_SIZE):
        offsets.append(int(eval(formula, {"__builtins__": {}}, {"t": t})))
    return offsets


def analyze_pattern(offsets):
    bank_to_addrs = {}
    for offset in offsets:
        bank = compute_bank(offset)
        if bank not in bank_to_addrs:
            bank_to_addrs[bank] = set()
        bank_to_addrs[bank].add(offset)

    wavefronts = 0
    total_conflicts = 0
    for bank_id in range(NUM_BANKS):
        distinct = len(bank_to_addrs.get(bank_id, set()))
        wavefronts = max(wavefronts, distinct)
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


# --- Bug 1: Fix gpu_config.json ---
config = {"num_banks": 32, "bank_width_bytes": 4, "warp_size": 32}
with open("/app/gpu_config.json", "w") as f:
    json.dump(config, f, indent=2)

# --- Bug 3: Fix kernels.json stride_7 formula ---
with open("/app/kernels.json") as f:
    kernels_data = json.load(f)

kernels_data["kernels"]["stride_7"]["access_formula"] = "t * 28"

with open("/app/kernels.json", "w") as f:
    json.dump(kernels_data, f, indent=2)

# --- Bug 2: Fix sim.py (we don't patch the file; we compute correctly here) ---

# --- Compute corrected metrics for all kernels ---
corrected_metrics = {}
for name, kernel in kernels_data["kernels"].items():
    if "access_explicit" in kernel:
        offsets = list(kernel["access_explicit"])
    else:
        offsets = evaluate_formula(kernel["access_formula"])
    corrected_metrics[name] = analyze_pattern(offsets)

# --- Optimization analysis for column_major ---
# Thread t reads row t, column c=0 from a 32x32 float tile.
# Access offset = (t * stride + c) * 4, with c=0 -> offset = t * stride * 4
# Bank = (t * stride) % 32

strategies = {}

# no_padding: stride=32
offsets_np = [t * 32 * 4 for t in range(WARP_SIZE)]
r = analyze_pattern(offsets_np)
strategies["no_padding"] = {
    "stride": 32,
    "wavefronts": r["wavefronts"],
    "total_conflicts": r["total_conflicts"],
}

# pad_1: stride=33
offsets_p1 = [t * 33 * 4 for t in range(WARP_SIZE)]
r = analyze_pattern(offsets_p1)
strategies["pad_1"] = {
    "stride": 33,
    "wavefronts": r["wavefronts"],
    "total_conflicts": r["total_conflicts"],
}

# pad_2: stride=34
offsets_p2 = [t * 34 * 4 for t in range(WARP_SIZE)]
r = analyze_pattern(offsets_p2)
strategies["pad_2"] = {
    "stride": 34,
    "wavefronts": r["wavefronts"],
    "total_conflicts": r["total_conflicts"],
}

# xor_swizzle: stride=32, physical column = col ^ row
# Thread t reads row t, column 0 -> physical column = 0 ^ t = t
# Offset = (t * 32 + (0 ^ t)) * 4 = (t * 32 + t) * 4 = t * 33 * 4
# For general column c: offset = (t * 32 + (c ^ t)) * 4
# Bank = (t * 32 + c ^ t) % 32 = (c ^ t) % 32 -> bijection -> conflict-free
# Using c=0 for concrete computation:
offsets_xor = [(t * 32 + (0 ^ t)) * 4 for t in range(WARP_SIZE)]
r = analyze_pattern(offsets_xor)
strategies["xor_swizzle"] = {
    "stride": 32,
    "wavefronts": r["wavefronts"],
    "total_conflicts": r["total_conflicts"],
}

# Best recommendation: xor_swizzle (conflict-free without memory overhead)
recommendation = "xor_swizzle"

# --- Also fix sim.py so validate.sh passes ---
sim_py_path = "/app/sim.py"
with open(sim_py_path) as f:
    sim_code = f.read()

sim_code = sim_code.replace(
    "        wavefronts += distinct  # accumulate wavefront contributions",
    "        wavefronts = max(wavefronts, distinct)  # max distinct addresses across banks",
)

with open(sim_py_path, "w") as f:
    f.write(sim_code)

# --- Write results.json ---
results = {
    "bugs_found": [
        {
            "file": "gpu_config.json",
            "description": "num_banks was set to 16 instead of 32. Modern GPUs with compute capability >= 2.0 have 32 shared memory banks.",
            "wrong_value": 16,
            "correct_value": 32,
        },
        {
            "file": "sim.py",
            "description": "Wavefronts were computed as the sum of distinct addresses across all banks instead of the maximum. Wavefronts represent the number of serialized memory transactions, which equals the maximum bank occupancy.",
            "wrong_value": "sum of distinct addresses per bank",
            "correct_value": "max of distinct addresses per bank",
        },
        {
            "file": "kernels.json",
            "description": "stride_7 kernel formula uses t * 24 (stride of 6 elements = 24 bytes) but the description specifies stride of 7 elements (28 bytes). The formula should be t * 28.",
            "wrong_value": "t * 24",
            "correct_value": "t * 28",
        },
    ],
    "corrected_metrics": corrected_metrics,
    "optimization_analysis": {
        "column_major": {
            "strategies": strategies,
            "recommendation": recommendation,
        }
    },
}

with open("/app/results.json", "w") as f:
    json.dump(results, f, indent=2)

print("Solution complete. Results written to /app/results.json")
print(f"Corrected metrics: {json.dumps(corrected_metrics, indent=2)}")
print(f"Optimization strategies: {json.dumps(strategies, indent=2)}")
print(f"Recommendation: {recommendation}")
