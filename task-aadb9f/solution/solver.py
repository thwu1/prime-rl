#!/usr/bin/env python3
"""
Solution: Fix the occupancy model bugs and architecture spec errors,
evaluate optimization proposals, implement find_optimal_block_size,
and generate correct predictions.
"""

import json
import math
import os
import subprocess
import sys

# ============================================================
# Step 0: Export SQLite measurements to CSV for model validation
# ============================================================
print("Exporting measurements from SQLite to CSV...")
subprocess.run([
    "sqlite3", "-header", "-csv",
    "/app/profiling/measurements.db",
    "SELECT arch,kernel,block_size,active_blocks_per_sm,active_warps_per_sm,occupancy,limiting_resource,valid FROM measurements;"
], stdout=open("/app/profiling/measurements.csv", "w"), check=True)

# ============================================================
# Step 0.5: Use arch_reference tool to identify spec errors
# ============================================================
print("\nComparing spec files against reference database...")
for spec_name in ["volta", "ampere", "hopper"]:
    result = subprocess.run(
        ["/app/tools/arch_reference", "compare", f"/app/specs/{spec_name}.json"],
        capture_output=True, text=True
    )
    print(f"  {spec_name}: {result.stdout.strip()}")

# ============================================================
# Step 1: Fix Bug 1 in model.py -- register allocation rounding
# ============================================================
model_path = "/app/model.py"
with open(model_path) as f:
    content = f.read()

old_reg_line = "regs_per_warp = (raw_regs_per_warp // reg_alloc_unit) * reg_alloc_unit"
new_reg_line = "regs_per_warp = math.ceil(raw_regs_per_warp / reg_alloc_unit) * reg_alloc_unit"
assert old_reg_line in content, "Could not find register rounding line to fix"
content = content.replace(old_reg_line, new_reg_line)

# Fix Bug 2: validity check should use max_shared_memory_per_block
old_validity = 'if smem_per_block > arch["max_shared_memory_per_multiprocessor"]:'
new_validity = 'if smem_per_block > arch["max_shared_memory_per_block"]:'
assert old_validity in content, "Could not find smem validity check to fix"
content = content.replace(old_validity, new_validity)

# ============================================================
# Step 1.5: Add find_optimal_block_size function to model.py
# ============================================================
optimal_func = '''

def find_optimal_block_size(arch, kernel):
    """Find the block size that maximizes occupancy.

    Searches all block sizes that are multiples of warp_size,
    from warp_size up to max_threads_per_block inclusive.

    Ties broken by: max active_blocks_per_sm, then smallest block_size.

    Returns dict with optimal_block_size, active_blocks_per_sm,
    occupancy, limiting_resource. If no valid config exists,
    returns {"error": "no_valid_configuration"}.
    """
    warp_size = arch["warp_size"]
    max_threads = arch["max_threads_per_block"]

    best = None
    for bs in range(warp_size, max_threads + 1, warp_size):
        result = compute_occupancy(arch, kernel, bs)
        if "error" in result:
            continue
        occ = result["occupancy"]
        blocks = result["active_blocks_per_sm"]
        if best is None:
            best = (occ, blocks, bs, result)
        else:
            # Maximize occupancy, then max blocks, then min block_size
            best_occ, best_blocks, best_bs, _ = best
            if (occ > best_occ + 1e-9 or
                (abs(occ - best_occ) < 1e-9 and blocks > best_blocks) or
                (abs(occ - best_occ) < 1e-9 and blocks == best_blocks and bs < best_bs)):
                best = (occ, blocks, bs, result)

    if best is None:
        return {"error": "no_valid_configuration"}

    _, _, optimal_bs, result = best
    return {
        "optimal_block_size": optimal_bs,
        "active_blocks_per_sm": result["active_blocks_per_sm"],
        "occupancy": result["occupancy"],
        "limiting_resource": result["limiting_resource"],
    }
'''

# Insert before the run_predictions function
insertion_point = "def run_predictions("
assert insertion_point in content
content = content.replace(insertion_point, optimal_func + "\n" + insertion_point)

with open(model_path, "w") as f:
    f.write(content)

print("\nFixed model.py: register rounding + smem validity + find_optimal_block_size")

# ============================================================
# Step 2: Fix Ampere architecture specification errors
# ============================================================
ampere_path = "/app/specs/ampere.json"
with open(ampere_path) as f:
    ampere = json.load(f)

ampere["register_alloc_unit_size"] = 256
ampere["max_shared_memory_per_block"] = 167936

with open(ampere_path, "w") as f:
    json.dump(ampere, f, indent=2)

print("Fixed ampere.json: register_alloc_unit_size + max_shared_memory_per_block")

# ============================================================
# Step 3: Validate fixes
# ============================================================
sys.path.insert(0, "/app")
if "model" in sys.modules:
    del sys.modules["model"]
import model

print("\nValidating fixes against measurements...")
mismatches = model.validate_against_measurements(
    "/app/specs", "/app/kernels",
    "/app/profiling/measurements.csv"
)
if mismatches:
    print(f"WARNING: {len(mismatches)} mismatches remain!")
    sys.exit(1)

# ============================================================
# Step 4: Generate predictions
# ============================================================
with open("/app/workloads.json") as f:
    workloads_data = json.load(f)

diagnostics = [
    {
        "file": "model.py",
        "issue": "Register allocation per warp uses floor division "
                 "(raw_regs_per_warp // reg_alloc_unit) instead of ceiling "
                 "division. This underallocates registers for kernels whose "
                 "registers_per_thread * warp_size is not an exact multiple "
                 "of the register allocation unit, causing the model to "
                 "overestimate occupancy.",
        "fix": "Changed to math.ceil(raw_regs_per_warp / reg_alloc_unit) * "
               "reg_alloc_unit to correctly round up to the next allocation "
               "unit boundary."
    },
    {
        "file": "model.py",
        "issue": "Shared memory validity check compares smem_per_block "
                 "against max_shared_memory_per_multiprocessor (the SM-wide "
                 "total) instead of max_shared_memory_per_block (the per-block "
                 "limit). This allows configurations that exceed the "
                 "per-block shared memory cap to pass validation.",
        "fix": "Changed validity check to compare against "
               "arch['max_shared_memory_per_block']."
    },
    {
        "file": "specs/ampere.json",
        "issue": "register_alloc_unit_size set to 128, but NVIDIA Ampere "
                 "A100 (SM 8.0) uses 256-register allocation granularity.",
        "fix": "Corrected register_alloc_unit_size from 128 to 256."
    },
    {
        "file": "specs/ampere.json",
        "issue": "max_shared_memory_per_block set to 101376, but the A100 "
                 "supports up to 167936 bytes of shared memory per block.",
        "fix": "Corrected max_shared_memory_per_block from 101376 to 167936."
    },
]

predictions = []
for wl in workloads_data["workloads"]:
    arch = model.load_arch_spec("/app/specs", wl["architecture"])
    kernel = model.load_kernel_spec("/app/kernels", wl["kernel"])
    result = model.compute_occupancy(arch, kernel, wl["block_size"])
    result["workload_id"] = wl["workload_id"]
    result["architecture"] = wl["architecture"]
    result["kernel"] = wl["kernel"]
    result["block_size"] = wl["block_size"]
    predictions.append(result)

# ============================================================
# Step 5: Evaluate optimization proposals
# ============================================================
print("\nEvaluating optimization proposals...")
with open("/app/proposals.json") as f:
    proposals_data = json.load(f)

optimization_evaluations = []
for prop in proposals_data["proposals"]:
    pid = prop["proposal_id"]
    arch = model.load_arch_spec("/app/specs", prop["architecture"])
    kernel = model.load_kernel_spec("/app/kernels", prop["kernel"])
    mod = prop["modification"]

    # Compute original occupancy
    original_result = model.compute_occupancy(arch, kernel, prop["block_size"])

    # Apply modification and compute proposed occupancy
    if mod["parameter"] == "block_size":
        proposed_result = model.compute_occupancy(arch, kernel, mod["proposed"])
    else:
        modified_kernel = dict(kernel)
        modified_kernel[mod["parameter"]] = mod["proposed"]
        proposed_result = model.compute_occupancy(arch, modified_kernel, prop["block_size"])

    # Determine verdict
    if "error" in proposed_result:
        verdict = "invalid"
        entry = {
            "proposal_id": pid,
            "verdict": verdict,
            "original_occupancy": original_result.get("occupancy", None),
            "reason": proposed_result.get("reason", "invalid_configuration"),
            "explanation": f"Proposed configuration is invalid: {proposed_result.get('reason', 'unknown')}",
        }
    else:
        orig_occ = original_result["occupancy"]
        prop_occ = proposed_result["occupancy"]
        if abs(prop_occ - orig_occ) < 1e-9:
            verdict = "neutral"
        elif prop_occ > orig_occ:
            verdict = "improves"
        else:
            verdict = "degrades"
        entry = {
            "proposal_id": pid,
            "verdict": verdict,
            "original_occupancy": orig_occ,
            "proposed_occupancy": prop_occ,
            "explanation": (
                f"Occupancy changes from {orig_occ:.4f} to {prop_occ:.4f} "
                f"({verdict}). Original limiting: {original_result['limiting_resource']}, "
                f"proposed limiting: {proposed_result['limiting_resource']}."
            ),
        }

    optimization_evaluations.append(entry)
    print(f"  Proposal {pid}: {verdict}")

# ============================================================
# Step 6: Find optimal configurations
# ============================================================
print("\nFinding optimal block sizes...")
optimal_pairs = [
    ("volta", "reduce_warp"),
    ("ampere", "fft_radix"),
    ("hopper", "stencil_3d"),
]

optimal_configurations = []
for arch_name, kernel_name in optimal_pairs:
    arch = model.load_arch_spec("/app/specs", arch_name)
    kernel = model.load_kernel_spec("/app/kernels", kernel_name)
    result = model.find_optimal_block_size(arch, kernel)
    result["architecture"] = arch_name
    result["kernel"] = kernel_name
    optimal_configurations.append(result)
    print(f"  {arch_name}/{kernel_name}: bs={result['optimal_block_size']}, "
          f"occ={result['occupancy']}")

# ============================================================
# Step 7: Write results
# ============================================================
output = {
    "diagnostics": diagnostics,
    "predictions": predictions,
    "optimization_evaluations": optimization_evaluations,
    "optimal_configurations": optimal_configurations,
}

with open("/app/results.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"\nWrote results to /app/results.json")
print("Done.")
