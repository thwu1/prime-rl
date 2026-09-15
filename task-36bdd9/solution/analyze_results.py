#!/usr/bin/env python3
"""
Parse Ramulator 2.0 simulation outputs, compute DDR4 timing parameters,
evaluate scheduling strategies, and write results.json.
"""

import json
import math
import re


# ─── DDR4 Timing Computation ───
# Replicate the logic from Ramulator 2.0's DDR4.cpp for DDR4_8Gb_x8 / DDR4_2400R


def compute_timing_analysis():
    """Compute DDR4 timing parameters exactly as the simulator does."""

    # DDR4_2400R preset values from DDR4.cpp timing_presets table
    rate = 2400
    nBL = 4
    nCL = 16
    nRCD = 16
    nRP = 16
    nRAS = 39
    nRC = 55
    nWR = 18
    nRTP = 9
    nCWL = 12
    nCCDS = 4
    nCCDL = 6
    nWTRS = 3
    nWTRL = 9
    nCS = 2

    # tCK_ps computed as integer division: 1E6 / (rate / 2)
    tCK_ps = int(1e6 / (rate / 2))  # = 833

    # JEDEC tables indexed by [dq_id][rate_id]
    # dq_id: 0=x4, 1=x8, 2=x16 -- DDR4_8Gb_x8 → dq_id=1
    # rate_id: 0=1600,1=1866,2=2133,3=2400,4=2666,5=2933,6=3200 → rate_id=3
    nRRDS_TABLE = [
        [4, 4, 4, 4, 4, 4, 4],       # x4
        [4, 4, 4, 4, 4, 4, 4],       # x8
        [5, 5, 6, 7, 8, 8, 9],       # x16
    ]
    nRRDL_TABLE = [
        [5, 5, 6, 6, 7, 8, 8],       # x4
        [5, 5, 6, 6, 7, 8, 8],       # x8
        [6, 6, 7, 8, 9, 10, 11],     # x16
    ]
    nFAW_TABLE = [
        [16, 16, 16, 16, 16, 16, 16],  # x4
        [20, 22, 23, 26, 28, 31, 34],  # x8
        [28, 28, 32, 36, 40, 44, 48],  # x16
    ]

    dq_id = 1   # x8
    rate_id = 3  # 2400

    nRRDS = nRRDS_TABLE[dq_id][rate_id]  # 4
    nRRDL = nRRDL_TABLE[dq_id][rate_id]  # 6
    nFAW = nFAW_TABLE[dq_id][rate_id]    # 26

    # Refresh timings — density_id=2 for 8Gb (8192 Mb)
    tRFC_TABLE = [160, 260, 360, 550]  # tRFC1 in ns for 2Gb/4Gb/8Gb/16Gb
    tREFI_BASE = 7800                   # ns

    density_id = 2  # 8Gb = 8192 Mb

    nRFC = math.ceil(tRFC_TABLE[density_id] * 1000 / tCK_ps)   # ceil(360000/833) = 433
    nREFI = math.ceil(tREFI_BASE * 1000 / tCK_ps)              # ceil(7800000/833) = 9364

    # Derived timing constraints from populate_timingcons in DDR4.cpp
    read_latency_cycles = nCL + nBL                        # 16+4 = 20
    rank_rd_to_wr_cycles = nCL + nBL + 2 - nCWL           # 16+4+2-12 = 10
    rank_wr_to_rd_cycles = nCWL + nBL + nWTRS              # 12+4+3 = 19

    return {
        "org": "DDR4_8Gb_x8",
        "timing": "DDR4_2400R",
        "nRRDS": nRRDS,
        "nRRDL": nRRDL,
        "nFAW": nFAW,
        "nRFC": nRFC,
        "nREFI": nREFI,
        "tCK_ps": tCK_ps,
        "read_latency_cycles": read_latency_cycles,
        "rank_rd_to_wr_cycles": rank_rd_to_wr_cycles,
        "rank_wr_to_rd_cycles": rank_wr_to_rd_cycles,
    }


# ─── Simulation Output Parsing ───


def parse_int_stat(text, stat_name):
    """Extract an integer statistic from Ramulator's YAML output."""
    m = re.search(rf"^\s*{re.escape(stat_name)}:\s*(\d+)", text, re.MULTILINE)
    return int(m.group(1)) if m else 0


def parse_simulation_output(filepath):
    """Parse key statistics from a single simulation output file."""
    with open(filepath) as f:
        text = f.read()
    return {
        "row_hits": parse_int_stat(text, "row_hits_0"),
        "row_misses": parse_int_stat(text, "row_misses_0"),
        "row_conflicts": parse_int_stat(text, "row_conflicts_0"),
    }


# ─── Evaluation Logic ───


def evaluate(simulations):
    """Determine optimal scheduler for each workload type."""

    frfcfs_seq = simulations["frfcfs_sequential"]
    fcfs_seq = simulations["fcfs_sequential"]
    frfcfs_rand = simulations["frfcfs_random"]
    fcfs_rand = simulations["fcfs_random"]

    # Optimal scheduler based on row buffer utilization
    seq_optimal = (
        "FRFCFS" if frfcfs_seq["row_hits"] >= fcfs_seq["row_hits"] else "FCFS"
    )
    rand_optimal = (
        "FRFCFS" if frfcfs_rand["row_hits"] >= fcfs_rand["row_hits"] else "FCFS"
    )

    # Compute FRFCFS row hit advantage for random workload
    total_requests = max(
        frfcfs_rand["row_hits"]
        + frfcfs_rand["row_misses"]
        + frfcfs_rand["row_conflicts"],
        1,
    )
    advantage_pct = max(
        0.0,
        (frfcfs_rand["row_hits"] - fcfs_rand["row_hits"]) / total_requests * 100,
    )

    return {
        "sequential_optimal_scheduler": seq_optimal,
        "random_optimal_scheduler": rand_optimal,
        "frfcfs_row_hit_advantage_random_pct": round(advantage_pct, 2),
        "design_rationale": (
            "FRFCFS outperforms FCFS because its First-Ready policy "
            "prioritizes requests whose DRAM commands can be issued "
            "immediately, avoiding idle cycles when timing constraints "
            "(nRRDS, nFAW, nRCD, etc.) block the oldest request. For "
            "random workloads, this matters because requests target "
            "different banks with varying timing states; FRFCFS selects "
            "a request to a non-blocked bank while FCFS stalls on the "
            "oldest timing-blocked request. FRFCFS also opportunistically "
            "exploits row buffer hits when multiple requests in the "
            "buffer target an already-open row, which pure FCFS misses."
        ),
    }


# ─── Main ───


def main():
    timing = compute_timing_analysis()

    sim_names = [
        "frfcfs_sequential",
        "fcfs_sequential",
        "frfcfs_random",
        "fcfs_random",
    ]
    simulations = {}
    for name in sim_names:
        filepath = f"/app/sim_output/{name}.txt"
        simulations[name] = parse_simulation_output(filepath)

    evaluation = evaluate(simulations)

    results = {
        "timing_analysis": timing,
        "simulations": simulations,
        "evaluation": evaluation,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")
    print()
    print("Timing analysis:")
    for k, v in timing.items():
        print(f"  {k}: {v}")
    print()
    print("Simulation results:")
    for name, stats in simulations.items():
        print(
            f"  {name}: hits={stats['row_hits']}, "
            f"misses={stats['row_misses']}, conflicts={stats['row_conflicts']}"
        )
    print()
    print("Evaluation:")
    for k, v in evaluation.items():
        if k != "design_rationale":
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
