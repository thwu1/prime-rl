#!/usr/bin/env python3
"""GPU Kernel Occupancy Prediction Model.

Predicts theoretical SM-level occupancy for CUDA kernels based on
architecture specifications and kernel resource profiles. The model
computes how many thread blocks can simultaneously reside on a single
streaming multiprocessor (SM) given the resource constraints.

Usage:
    python3 model.py predict --workloads <path> --output <path>
    python3 model.py validate --measurements <path>
"""

import argparse
import csv
import json
import math
import os
import sys


def load_arch_spec(specs_dir, arch_name):
    """Load GPU architecture specification from JSON file."""
    path = os.path.join(specs_dir, f"{arch_name}.json")
    with open(path) as f:
        return json.load(f)


def load_kernel_spec(kernels_dir, kernel_name):
    """Load kernel resource profile from JSON file."""
    path = os.path.join(kernels_dir, f"{kernel_name}.json")
    with open(path) as f:
        return json.load(f)


def _eval_smem_formula(formula, warps_per_block, block_size):
    """Safely evaluate a shared memory formula string."""
    allowed = {
        "warps_per_block": warps_per_block,
        "block_size": block_size,
    }
    return eval(formula, {"__builtins__": {}}, allowed)


def compute_occupancy(arch, kernel, block_size):
    """Compute theoretical occupancy for a kernel launch configuration.

    Determines the maximum number of thread blocks that can co-reside on
    a single SM, based on register usage, shared memory usage, warp limits,
    thread limits, and the per-SM block cap.

    Args:
        arch: Architecture specification dict.
        kernel: Kernel resource profile dict.
        block_size: Number of threads per block.

    Returns:
        Dict with occupancy metrics, or error dict for invalid configs.
    """
    warp_size = arch["warp_size"]
    max_threads_per_block = arch["max_threads_per_block"]

    # Validate block size
    if block_size > max_threads_per_block:
        return {
            "error": "invalid_configuration",
            "reason": "block_size_exceeds_max_threads_per_block",
        }
    if block_size <= 0:
        return {
            "error": "invalid_configuration",
            "reason": "block_size_must_be_positive",
        }

    # Compute warps per block (ceiling for partial warps)
    warps_per_block = (block_size + warp_size - 1) // warp_size

    # ---- Register allocation ----
    # Each warp's register usage is rounded up to the allocation granularity.
    reg_alloc_unit = arch["register_alloc_unit_size"]
    regs_per_thread = kernel["registers_per_thread"]
    raw_regs_per_warp = regs_per_thread * warp_size

    # Align to allocation unit boundary
    regs_per_warp = (raw_regs_per_warp // reg_alloc_unit) * reg_alloc_unit
    if regs_per_warp == 0 and regs_per_thread > 0:
        regs_per_warp = reg_alloc_unit

    regs_per_block = regs_per_warp * warps_per_block

    # ---- Shared memory allocation ----
    smem_bytes = kernel.get("shared_memory_bytes", 0)
    if "shared_memory_bytes_formula" in kernel:
        smem_bytes = _eval_smem_formula(
            kernel["shared_memory_bytes_formula"],
            warps_per_block, block_size
        )

    smem_alloc_unit = arch["shared_memory_alloc_unit_size"]
    if smem_bytes > 0:
        smem_per_block = math.ceil(smem_bytes / smem_alloc_unit) * smem_alloc_unit
    else:
        smem_per_block = 0

    # Validate shared memory does not exceed the per-SM maximum
    if smem_per_block > 0:
        if smem_per_block > arch["max_shared_memory_per_multiprocessor"]:
            return {
                "error": "invalid_configuration",
                "reason": "shared_memory_per_block_exceeded",
            }

    # ---- Resource limits ----
    max_regs_per_sm = arch["max_registers_per_multiprocessor"]
    max_smem_per_sm = arch["max_shared_memory_per_multiprocessor"]
    max_warps_per_sm = arch["max_warps_per_multiprocessor"]
    max_threads_per_sm = arch["max_threads_per_multiprocessor"]
    max_blocks_per_sm = arch["max_thread_blocks_per_multiprocessor"]

    # Register limit: how many blocks fit given register file size
    if regs_per_block > 0:
        limit_regs = max_regs_per_sm // regs_per_block
    else:
        limit_regs = max_blocks_per_sm

    # Shared memory limit
    if smem_per_block > 0:
        limit_smem = max_smem_per_sm // smem_per_block
    else:
        limit_smem = None  # shared memory does not constrain

    # Warp limit
    limit_warps = max_warps_per_sm // warps_per_block

    # Thread limit
    limit_threads = max_threads_per_sm // block_size

    # Max blocks hardware limit
    limit_max_blocks = max_blocks_per_sm

    # ---- Determine active blocks ----
    limits = {
        "registers": limit_regs,
        "warps": limit_warps,
        "threads": limit_threads,
        "max_blocks": limit_max_blocks,
    }
    if limit_smem is not None:
        limits["shared_memory"] = limit_smem

    active_blocks = min(limits.values())
    if active_blocks <= 0:
        return {
            "error": "invalid_configuration",
            "reason": "zero_active_blocks",
        }

    # Determine which resource is the bottleneck.
    # When multiple resources tie at the minimum, use hardware priority order.
    priority_order = ["registers", "shared_memory", "warps", "threads", "max_blocks"]
    limiting_resource = None
    for resource in priority_order:
        if resource in limits and limits[resource] == active_blocks:
            limiting_resource = resource
            break

    active_warps = active_blocks * warps_per_block
    occupancy = active_warps / max_warps_per_sm

    return {
        "active_blocks_per_sm": active_blocks,
        "active_warps_per_sm": active_warps,
        "occupancy": round(occupancy, 6),
        "limiting_resource": limiting_resource,
    }


def run_predictions(specs_dir, kernels_dir, workloads_path, output_path,
                    diagnostics=None):
    """Generate occupancy predictions for a set of workloads."""
    with open(workloads_path) as f:
        workloads_data = json.load(f)

    predictions = []
    for wl in workloads_data["workloads"]:
        arch = load_arch_spec(specs_dir, wl["architecture"])
        kernel = load_kernel_spec(kernels_dir, wl["kernel"])
        result = compute_occupancy(arch, kernel, wl["block_size"])
        result["workload_id"] = wl["workload_id"]
        result["architecture"] = wl["architecture"]
        result["kernel"] = wl["kernel"]
        result["block_size"] = wl["block_size"]
        predictions.append(result)

    output = {
        "diagnostics": diagnostics if diagnostics is not None else [],
        "predictions": predictions,
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {len(predictions)} predictions to {output_path}")


def validate_against_measurements(specs_dir, kernels_dir, measurements_path):
    """Compare model predictions against hardware measurements.

    Reads a CSV of ground-truth measurements and reports mismatches.
    """
    mismatches = []
    total = 0
    with open(measurements_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            arch = load_arch_spec(specs_dir, row["arch"])
            kernel = load_kernel_spec(kernels_dir, row["kernel"])
            block_size = int(row["block_size"])
            result = compute_occupancy(arch, kernel, block_size)

            is_valid = row["valid"].strip().lower() == "true"

            if not is_valid:
                # Measurement says invalid — model should agree
                if "error" not in result:
                    mismatches.append({
                        "config": f"{row['arch']}/{row['kernel']}/bs={block_size}",
                        "expected": "invalid_configuration",
                        "predicted": result,
                    })
            else:
                if "error" in result:
                    mismatches.append({
                        "config": f"{row['arch']}/{row['kernel']}/bs={block_size}",
                        "expected": {
                            "blocks": int(row["active_blocks_per_sm"]),
                            "occ": float(row["occupancy"]),
                        },
                        "predicted": result,
                    })
                else:
                    exp_blocks = int(row["active_blocks_per_sm"])
                    exp_warps = int(row["active_warps_per_sm"])
                    exp_occ = float(row["occupancy"])
                    exp_lim = row["limiting_resource"].strip()

                    pred_ok = (
                        result["active_blocks_per_sm"] == exp_blocks
                        and result["active_warps_per_sm"] == exp_warps
                        and abs(result["occupancy"] - exp_occ) < 1e-4
                        and result["limiting_resource"] == exp_lim
                    )
                    if not pred_ok:
                        mismatches.append({
                            "config": f"{row['arch']}/{row['kernel']}/bs={block_size}",
                            "expected": {
                                "blocks": exp_blocks,
                                "warps": exp_warps,
                                "occ": exp_occ,
                                "lim": exp_lim,
                            },
                            "predicted": {
                                "blocks": result["active_blocks_per_sm"],
                                "warps": result["active_warps_per_sm"],
                                "occ": result["occupancy"],
                                "lim": result["limiting_resource"],
                            },
                        })

    print(f"Validated {total} measurements.")
    if mismatches:
        print(f"\n{len(mismatches)} MISMATCHES found:\n")
        for m in mismatches:
            print(f"  {m['config']}:")
            print(f"    Expected:  {m['expected']}")
            print(f"    Predicted: {m['predicted']}")
            print()
    else:
        print("All predictions match measurements. Model is correct.")

    return mismatches


def main():
    parser = argparse.ArgumentParser(
        description="GPU Kernel Occupancy Prediction Model"
    )
    parser.add_argument(
        "--specs-dir", default="/app/specs",
        help="Directory containing architecture spec JSON files",
    )
    parser.add_argument(
        "--kernels-dir", default="/app/kernels",
        help="Directory containing kernel spec JSON files",
    )

    sub = parser.add_subparsers(dest="command")

    p_pred = sub.add_parser("predict", help="Generate predictions")
    p_pred.add_argument("--workloads", required=True,
                        help="Path to workloads JSON")
    p_pred.add_argument("--output", required=True,
                        help="Path to write results JSON")

    p_val = sub.add_parser("validate",
                           help="Validate against measurements")
    p_val.add_argument("--measurements", required=True,
                       help="Path to measurements CSV")

    args = parser.parse_args()

    if args.command == "predict":
        run_predictions(
            args.specs_dir, args.kernels_dir,
            args.workloads, args.output,
        )
    elif args.command == "validate":
        mismatches = validate_against_measurements(
            args.specs_dir, args.kernels_dir, args.measurements,
        )
        sys.exit(1 if mismatches else 0)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
