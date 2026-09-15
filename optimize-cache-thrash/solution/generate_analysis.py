#!/usr/bin/env python3
"""Parse cachegrind output file and generate /app/analysis.json.

Runs valgrind --tool=cachegrind on the original (unoptimized) binary,
parses the raw cachegrind.out file to extract per-function D-cache
statistics, reads the L1D cache configuration, classifies each kernel,
and writes the structured analysis report.
"""

import os
import re
import json
import glob
import subprocess

TARGET_KERNELS = [
    "analyze_sensors",
    "normalize_data",
    "compute_distances",
    "smooth_data",
]

CLASSIFICATION_THRESHOLD = 10.0  # % D1 read miss rate


def get_cache_config_from_sysfs():
    """Read L1 data cache configuration from sysfs."""
    try:
        base = "/sys/devices/system/cpu/cpu0/cache"
        for idx_dir in sorted(glob.glob(os.path.join(base, "index*"))):
            type_path = os.path.join(idx_dir, "type")
            if not os.path.exists(type_path):
                continue
            with open(type_path) as f:
                ctype = f.read().strip()
            if ctype == "Data":
                with open(os.path.join(idx_dir, "size")) as f:
                    s = f.read().strip()
                    if "K" in s:
                        size = int(s.replace("K", "")) * 1024
                    elif "M" in s:
                        size = int(s.replace("M", "")) * 1024 * 1024
                    else:
                        size = int(s)
                with open(os.path.join(idx_dir, "coherency_line_size")) as f:
                    line_bytes = int(f.read().strip())
                with open(os.path.join(idx_dir, "ways_of_associativity")) as f:
                    assoc = int(f.read().strip())
                return {
                    "l1d_size_bytes": size,
                    "l1d_line_bytes": line_bytes,
                    "l1d_associativity": assoc,
                }
    except Exception:
        pass
    return None


def parse_cachegrind_output(cg_file):
    """Parse raw cachegrind.out.* file for per-function D-cache stats.

    Returns (cache_config_dict, {fn_name: {event: count, ...}}).
    """
    cache_config = {}
    events = []
    functions = {}
    current_fn = None

    with open(cg_file) as f:
        for line in f:
            line = line.rstrip("\n")

            # Cache configuration from desc: lines
            if line.startswith("desc: D1 cache:"):
                m = re.search(
                    r"(\d[\d,]*)\s*B,\s*(\d+)-way,\s*(\d+)\s*B", line
                )
                if m:
                    cache_config = {
                        "l1d_size_bytes": int(m.group(1).replace(",", "")),
                        "l1d_associativity": int(m.group(2)),
                        "l1d_line_bytes": int(m.group(3)),
                    }

            # Event names header
            elif line.startswith("events:"):
                events = line.split()[1:]

            # Function marker
            elif line.startswith("fn="):
                current_fn = line[3:]
                if current_fn not in functions:
                    functions[current_fn] = {e: 0 for e in events}

            # File/object markers — don't reset current_fn
            elif line.startswith("fl=") or line.startswith("ob="):
                pass

            # Data line: line_number count1 count2 ...
            elif current_fn and events and line and line[0].isdigit():
                parts = line.split()
                if len(parts) >= len(events) + 1:
                    for i, e in enumerate(events):
                        functions[current_fn][e] += int(parts[i + 1])

    return cache_config, functions


def main():
    os.chdir("/app")

    # Step 1: Run cachegrind on the original (unoptimized) binary
    cg_outfile = "/app/cachegrind.out"
    print("Running cachegrind on /app/.original/pipeline ...")
    result = subprocess.run(
        [
            "valgrind",
            "--tool=cachegrind",
            "--cache-sim=yes",
            f"--cachegrind-out-file={cg_outfile}",
            "/app/.original/pipeline",
            "42",
            "/tmp/cg_analysis_out.txt",
        ],
        capture_output=True,
        timeout=300,
    )
    print(result.stderr.decode()[-500:])

    # Locate the output file
    if not os.path.exists(cg_outfile):
        candidates = sorted(
            glob.glob("/app/cachegrind.out.*"), key=os.path.getmtime
        )
        if candidates:
            cg_outfile = candidates[-1]
        else:
            print("ERROR: No cachegrind output file found")
            return

    # Step 2: Parse the cachegrind output
    cg_cache_config, functions = parse_cachegrind_output(cg_outfile)

    # Step 3: Determine cache configuration
    cache_config = cg_cache_config or get_cache_config_from_sysfs()
    if not cache_config:
        cache_config = {
            "l1d_size_bytes": 32768,
            "l1d_line_bytes": 64,
            "l1d_associativity": 8,
        }

    # Step 4: Extract per-kernel D1 read miss rates and classify
    kernel_profiles = {}
    d1_miss_totals = {}

    for kernel in TARGET_KERNELS:
        if kernel in functions:
            dr = functions[kernel].get("Dr", 0)
            d1mr = functions[kernel].get("D1mr", 0)
            miss_rate = (d1mr / dr * 100.0) if dr > 0 else 0.0
            classification = (
                "cache_bound"
                if miss_rate > CLASSIFICATION_THRESHOLD
                else "compute_bound"
            )
            kernel_profiles[kernel] = {
                "d1_read_miss_rate_pct": round(miss_rate, 2),
                "classification": classification,
            }
            d1_miss_totals[kernel] = d1mr
        else:
            print(f"WARNING: kernel '{kernel}' not found in cachegrind output")
            kernel_profiles[kernel] = {
                "d1_read_miss_rate_pct": 0.0,
                "classification": "compute_bound",
            }
            d1_miss_totals[kernel] = 0

    # Step 5: Determine most cache-impactful kernel
    cache_bound_misses = {
        k: d1_miss_totals[k]
        for k in TARGET_KERNELS
        if kernel_profiles[k]["classification"] == "cache_bound"
    }
    most_impactful = (
        max(cache_bound_misses, key=cache_bound_misses.get)
        if cache_bound_misses
        else TARGET_KERNELS[0]
    )

    # Step 6: Write analysis.json
    analysis = {
        "cache_config": cache_config,
        "kernel_profiles": kernel_profiles,
        "most_cache_impactful": most_impactful,
    }

    with open("/app/analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)

    print("\nAnalysis written to /app/analysis.json:")
    print(json.dumps(analysis, indent=2))


if __name__ == "__main__":
    main()
