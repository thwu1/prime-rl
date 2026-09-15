#!/usr/bin/env python3
"""
Orchestrate the 8086 microcode simulator and Verilog cross-validation pipeline.

Steps:
  1. Run Python microcode simulator  → arithmetic results + traces
  2. Compile CORX Verilog with iverilog
  3. Simulate with vvp               → VCD waveform
  4. Parse VCD waveform              → Verilog trace
  5. Merge and write results.json

"""

import json
import subprocess
import sys
import os

os.chdir("/app")
sys.path.insert(0, "/app")


def main():
    # ---------- Step 1: Python microcode simulator ----------
    print("[1/4] Running Python microcode simulator...")
    from simulator import get_all_results
    results = get_all_results()

    # ---------- Step 2: Compile Verilog ----------
    print("[2/4] Compiling CORX Verilog with Icarus Verilog...")
    proc = subprocess.run(
        ["iverilog", "-o", "/app/corx_sim", "/app/corx_tb.v", "/app/corx.v"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print("iverilog FAILED:", proc.stderr, file=sys.stderr)
        sys.exit(1)

    # ---------- Step 3: Run VVP simulation ----------
    print("[3/4] Running VVP simulation...")
    proc = subprocess.run(
        ["vvp", "/app/corx_sim"],
        capture_output=True, text=True, cwd="/app",
    )
    if proc.returncode != 0:
        print("vvp FAILED:", proc.stderr, file=sys.stderr)
        sys.exit(1)
    print(proc.stdout.strip())

    # ---------- Step 4: Parse VCD waveform ----------
    print("[4/4] Parsing VCD waveform...")
    from parse_vcd import extract_corx_trace
    vcd_data = extract_corx_trace("/app/corx_sim.vcd")

    results["verilog_mul_trace"] = vcd_data["trace"]
    results["verilog_product"]   = vcd_data["product"]

    # ---------- Write combined results ----------
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Wrote /app/results.json")


if __name__ == "__main__":
    main()
