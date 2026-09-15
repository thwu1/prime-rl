#!/usr/bin/env python3
"""
Solution helper: fixes all bugs, implements Sklansky adder, runs synthesis,
and generates the analysis report.

"""

import json
import os
import re
import shutil
import subprocess
import sys


def fix_file(path, old, new):
    with open(path, "r") as f:
        content = f.read()
    if old not in content:
        print(f"WARNING: pattern not found in {path}")
        return False
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    return True


def main():
    os.chdir("/app")

    # ================================================================
    # 1. Fix ring oscillator: AND gate -> NAND gate in feedback path
    #    The original has an even number of inversions (30 inverters + 0
    #    from AND = 30, even -> no oscillation). Fix: use NAND for the
    #    enable gate so total inversions = 30 + 1 = 31 (odd).
    # ================================================================
    print(">>> Fixing ring oscillator feedback path...")
    fix_file(
        "rtl/ring_oscillator.v",
        "assign #1 chain[0] = enable & chain[NUM_INV-1];",
        "assign #1 chain[0] = ~(enable & chain[NUM_INV-1]);",
    )

    # ================================================================
    # 2. Fix Kogge-Stone adder: stage 2 uses p0[i] (bit-level propagate)
    #    instead of p1[i] (group propagate over 2 positions). This causes
    #    incorrect carry propagation when position i propagates but
    #    position i-1 does not.
    # ================================================================
    print(">>> Fixing Kogge-Stone prefix tree stage 2...")
    fix_file(
        "rtl/kogge_stone_adder.v",
        "assign g2[i] = g1[i] | (p0[i] & g1[i-2]);",
        "assign g2[i] = g1[i] | (p1[i] & g1[i-2]);",
    )

    # ================================================================
    # 3. Fix Brent-Kung adder: backward propagation for position 6
    #    incorrectly uses G_3_0 instead of G_5_0. This misses carry
    #    from positions 4-5 reaching position 6.
    # ================================================================
    print(">>> Fixing Brent-Kung backward propagation for position 6...")
    fix_file(
        "rtl/brent_kung_adder.v",
        "assign G_6_0 = G0[6] | (P0[6] & G_3_0);",
        "assign G_6_0 = G0[6] | (P0[6] & G_5_0);",
    )

    # ================================================================
    # 4. Install the Sklansky adder implementation
    # ================================================================
    print(">>> Installing Sklansky adder implementation...")
    shutil.copy("/solution/sklansky_adder_impl.v", "rtl/sklansky_adder.v")

    # ================================================================
    # 5. Fix adder_characterizer: widen counters from 16 to 32 bits
    #    and connect the Sklansky adder
    # ================================================================
    print(">>> Fixing adder characterizer counter widths and Sklansky connection...")
    with open("rtl/adder_characterizer.v", "r") as f:
        charz = f.read()

    # Widen osc_count port
    charz = charz.replace(
        "output reg  [15:0] osc_count",
        "output reg  [31:0] osc_count",
    )
    # Widen cycle_count register
    charz = charz.replace(
        "reg [15:0] cycle_count;",
        "reg [31:0] cycle_count;",
    )
    # Fix reset values
    charz = charz.replace("osc_count        <= 16'd0;", "osc_count        <= 32'd0;")
    charz = charz.replace("cycle_count      <= 16'd0;", "cycle_count      <= 32'd0;")

    # Connect Sklansky adder: remove stub, add real instantiation
    charz = charz.replace(
        "    // Sklansky adder (not yet connected)\n"
        "    // sklansky_adder #(.WIDTH(8)) u_sklansky (\n"
        "    //     .a(operand_a), .b(operand_b), .cin(cin),\n"
        "    //     .sum(sum_sklansky), .cout(cout_sklansky)\n"
        "    // );\n"
        "    assign sum_sklansky = 8'b0;\n"
        "    assign cout_sklansky = 1'b0;",
        "    sklansky_adder #(.WIDTH(8)) u_sklansky (\n"
        "        .a(operand_a), .b(operand_b), .cin(cin),\n"
        "        .sum(sum_sklansky), .cout(cout_sklansky)\n"
        "    );",
    )

    with open("rtl/adder_characterizer.v", "w") as f:
        f.write(charz)

    # ================================================================
    # 6. Verify all adders pass simulation
    # ================================================================
    adders = {
        "ripple_carry": ("TEST_RIPPLE", "ripple_carry_adder"),
        "kogge_stone": ("TEST_KOGGE", "kogge_stone_adder"),
        "brent_kung": ("TEST_BRENT", "brent_kung_adder"),
        "sklansky": ("TEST_SKLANSKY", "sklansky_adder"),
    }

    # Reuse the verification testbench from /tests/ if available,
    # otherwise use the one in tb/
    verify_tb = "/tests/verify_adder.v"
    if not os.path.exists(verify_tb):
        verify_tb = "tb/tb_adder.v"

    results = {}
    for name, (define, module) in adders.items():
        print(f">>> Verifying {name}...")
        r = subprocess.run(
            f"iverilog -D{define} -o /tmp/sim_{name} {verify_tb} rtl/{module}.v "
            f"&& vvp /tmp/sim_{name}",
            shell=True, capture_output=True, text=True, timeout=120,
        )
        passed = "RESULT: PASS" in r.stdout or "TEST PASSED" in r.stdout
        if not passed:
            print(f"  FAIL: {r.stdout.strip()}")
        else:
            print(f"  PASS")
        results[name] = {"correct": passed}

    # Verify ring oscillator
    print(">>> Verifying ring oscillator...")
    rosc_tb = "/tests/verify_ring_osc.v"
    if not os.path.exists(rosc_tb):
        rosc_tb = "tb/tb_ring_osc.v"
    r = subprocess.run(
        f"iverilog -o /tmp/sim_rosc {rosc_tb} rtl/ring_oscillator.v && vvp /tmp/sim_rosc",
        shell=True, capture_output=True, text=True, timeout=60,
    )
    rosc_ok = "RESULT: PASS" in r.stdout or "WORKING" in r.stdout
    print(f"  {'PASS' if rosc_ok else 'FAIL'}: {r.stdout.strip()}")

    # ================================================================
    # 7. Run Yosys synthesis for each adder
    # ================================================================
    os.makedirs("results", exist_ok=True)
    for name, (_, module) in adders.items():
        print(f">>> Synthesizing {module}...")
        log_path = f"results/{module}_synth.log"
        script = (
            f"read_verilog rtl/{module}.v; "
            f"synth -top {module}; "
            f"tee -o {log_path} stat"
        )
        subprocess.run(
            f'echo "{script}" | yosys -s -',
            shell=True, capture_output=True, text=True, timeout=120,
        )
        # Parse cell count from synthesis log
        cell_count = 0
        if os.path.exists(log_path):
            with open(log_path) as f:
                for line in f:
                    m = re.search(r"Number of cells:\s+(\d+)", line)
                    if m:
                        cell_count = int(m.group(1))
                        break
        results[name]["cell_count"] = cell_count
        print(f"  Cells: {cell_count}")

    # ================================================================
    # 8. Generate analysis.json
    # ================================================================
    # Sort adders by cell count for area ranking
    ranked = sorted(results.keys(), key=lambda n: results[n].get("cell_count", 0))

    analysis = {
        "adders": {
            name: {
                "cell_count": results[name]["cell_count"],
                "correct": results[name]["correct"],
            }
            for name in results
        },
        "area_ranking": ranked,
        "ring_oscillator_functional": rosc_ok,
    }

    with open("results/analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)

    print(f"\n>>> Results written to results/analysis.json")
    print(json.dumps(analysis, indent=2))

    # Exit with error if anything failed
    all_ok = all(r["correct"] for r in results.values()) and rosc_ok
    if not all_ok:
        print("\nERROR: Some components failed verification!")
        sys.exit(1)
    print("\nAll components verified successfully.")


if __name__ == "__main__":
    main()
