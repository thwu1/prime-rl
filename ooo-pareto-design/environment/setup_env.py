#!/usr/bin/env python3
"""Generate gem5-format simulation output files and calibration data.

Creates /app/sim_output/ with stats.txt files for all 108 processor
configurations (4 workloads each), and /app/calibration.csv with
known-good power measurements for model validation.
"""

import math
import os

WIDTHS = [4, 8, 12]
ROBS = [32, 64, 128, 256]
INTS = [64, 128, 256]
FPS = [64, 128, 256]
WORKLOADS = ['bfs', 'bubble_sort', 'matrix_multiply', 'nqueens']

INST_COUNTS = {
    'bfs': 5000000,
    'bubble_sort': 8000000,
    'matrix_multiply': 12000000,
    'nqueens': 6000000,
}

BRANCH_COUNTS = {
    'bfs': 1200000,
    'bubble_sort': 3500000,
    'matrix_multiply': 400000,
    'nqueens': 2000000,
}

L1D_ACCESS_COUNTS = {
    'bfs': 2500000,
    'bubble_sort': 4000000,
    'matrix_multiply': 6000000,
    'nqueens': 2000000,
}

BRANCH_MISPREDICT_RATES = {
    'bfs': 0.08,
    'bubble_sort': 0.12,
    'matrix_multiply': 0.02,
    'nqueens': 0.06,
}


def ipc_model(w, r, i, f, workload):
    log2_w = math.log2(w)
    log2_r = math.log2(r)
    log2_i = math.log2(i)
    log2_f = math.log2(f)

    if workload == 'bfs':
        ipc_w = 0.6 + 0.15 * log2_w
        ipc_r = 0.1 + 0.1 * log2_r
        ipc_i = 0.6 + 0.08 * log2_i
        ipc_f = 100.0
    elif workload == 'bubble_sort':
        ipc_w = 0.82 + 0.02 * log2_w
        ipc_r = 0.95 + 0.01 * log2_r
        ipc_i = 1.0 + 0.01 * log2_i
        ipc_f = 100.0
    elif workload == 'matrix_multiply':
        ipc_w = 2.5 + 0.06 * log2_w
        ipc_r = 2.5 + 0.04 * log2_r
        ipc_i = 2.5 + 0.03 * log2_i
        ipc_f = 0.5 + 0.2 * log2_f
    elif workload == 'nqueens':
        ipc_w = 1.2 + 0.05 * log2_w
        ipc_r = 1.1 + 0.03 * log2_r
        ipc_i = 0.4 + 0.1 * log2_i
        ipc_f = 100.0
    else:
        raise ValueError(f"Unknown workload: {workload}")

    return round(min(ipc_w, ipc_r, ipc_i, ipc_f), 6)


def l1_miss_rate_model(w, r, workload):
    log2_w = math.log2(w)
    log2_r = math.log2(r)

    if workload == 'bfs':
        rate = 0.22 - 0.008 * (log2_r - 5)
    elif workload == 'bubble_sort':
        rate = 0.015 + 0.002 * (log2_w - 2)
    elif workload == 'matrix_multiply':
        rate = 0.085 - 0.005 * (log2_r - 5) + 0.003 * (log2_w - 2)
    elif workload == 'nqueens':
        rate = 0.025 - 0.003 * (log2_r - 5)
    else:
        raise ValueError(f"Unknown workload: {workload}")

    return max(0.005, round(rate, 6))


def compute_area(w, r, i, f):
    return (
        w * (2 * r + i + f)
        + 4 * w
        + 2 * r
        + i
        + f
    )


def compute_power_correct(w, r, i, f, avg_ipc, avg_l1_miss, temperature=350):
    """Correct power model used only for calibration data generation."""
    V, freq = 0.9, 1.0
    activity = (avg_ipc / w) * (1.0 + 0.1 * w)
    stall_factor = 1.0 / (1.0 + 2.0 * avg_l1_miss)
    C_eff = 0.5 * (r + 2.0 * w * w)
    dynamic = C_eff * V * V * freq * activity * stall_factor
    area = compute_area(w, r, i, f)
    k = 0.002
    temp_factor = math.exp(k * (temperature - 300))
    leakage = 0.001 * area * temp_factor
    return round(dynamic + leakage, 4)


def generate_stats_file(config_id, w, r, i, f, output_dir):
    """Generate a gem5-format stats.txt for one configuration."""
    config_dir = os.path.join(output_dir, config_id)
    os.makedirs(config_dir, exist_ok=True)

    lines = []
    for wl in WORKLOADS:
        ipc = ipc_model(w, r, i, f, wl)
        insts = INST_COUNTS[wl]
        cycles = int(round(insts / ipc))
        sim_seconds = cycles * 1e-9

        l1_rate = l1_miss_rate_model(w, r, wl)
        l1_total = L1D_ACCESS_COUNTS[wl]
        l1_misses = int(round(l1_total * l1_rate))
        l1_hits = l1_total - l1_misses

        l2_total = l1_misses
        l2_hit_frac = max(0.30, 0.65 - 0.05 * (math.log2(w) - 2))
        l2_hits = int(round(l2_total * l2_hit_frac))
        l2_misses = l2_total - l2_hits

        bp_rate = BRANCH_MISPREDICT_RATES[wl]
        bp_total = BRANCH_COUNTS[wl]
        bp_incorrect = int(round(bp_total * bp_rate))

        l1i_hits = int(insts * 0.98)
        l1i_misses = int(insts * 0.02)
        rob_reads = int(2.2 * insts)
        iq_issued = int(1.05 * insts)
        squashed = int(0.04 * insts)
        mem_reads = l2_misses + int(0.1 * l2_misses)
        mem_writes = int(0.2 * mem_reads)
        avg_miss_lat = round(42.5 + 15.0 * (math.log2(w) - 2), 1)
        host_secs = round(45.0 + cycles * 1e-7, 2)
        host_tick_rate = int(1e12 / max(host_secs, 1))

        lines.append(
            f"---------- Begin Simulation Statistics [{wl}] ----------"
        )
        lines.append(
            f"sim_seconds                                              "
            f"{sim_seconds:.9f}"
        )
        lines.append(
            f"sim_ticks                                                "
            f"{int(sim_seconds * 1e12)}"
        )
        lines.append(
            f"host_seconds                                             "
            f"{host_secs}"
        )
        lines.append(
            f"host_tick_rate                                           "
            f"{host_tick_rate}"
        )
        lines.append(
            f"sim_insts                                                "
            f"{insts}"
        )
        lines.append(
            f"system.cpu.committedInsts                                "
            f"{insts}"
        )
        lines.append(
            f"system.cpu.numCycles                                     "
            f"{cycles}"
        )
        lines.append(
            f"system.cpu.fetchWidth                                    "
            f"{w}"
        )
        lines.append(
            f"system.cpu.numROBEntries                                 "
            f"{r}"
        )
        lines.append(
            f"system.cpu.numPhysIntRegs                                "
            f"{i}"
        )
        lines.append(
            f"system.cpu.numPhysFloatRegs                              "
            f"{f}"
        )
        lines.append(
            f"system.cpu.branchPred.condPredicted                      "
            f"{bp_total}"
        )
        lines.append(
            f"system.cpu.branchPred.condIncorrect                      "
            f"{bp_incorrect}"
        )
        lines.append(
            f"system.cpu.iq.iqInstsIssued                              "
            f"{iq_issued}"
        )
        lines.append(
            f"system.cpu.rename.squashedInsts                          "
            f"{squashed}"
        )
        lines.append(
            f"system.cpu.rob.reads                                     "
            f"{rob_reads}"
        )
        lines.append(
            f"board.cache_hierarchy.ruby_system."
            f"l1_controllers0.L1Icache.m_demand_hits     "
            f"{l1i_hits}"
        )
        lines.append(
            f"board.cache_hierarchy.ruby_system."
            f"l1_controllers0.L1Icache.m_demand_misses   "
            f"{l1i_misses}"
        )
        lines.append(
            f"board.cache_hierarchy.ruby_system."
            f"l1_controllers0.L1Dcache.m_demand_hits     "
            f"{l1_hits}"
        )
        lines.append(
            f"board.cache_hierarchy.ruby_system."
            f"l1_controllers0.L1Dcache.m_demand_misses   "
            f"{l1_misses}"
        )
        lines.append(
            f"board.cache_hierarchy.ruby_system."
            f"l2_controllers0.L2cache.m_demand_hits      "
            f"{l2_hits}"
        )
        lines.append(
            f"board.cache_hierarchy.ruby_system."
            f"l2_controllers0.L2cache.m_demand_misses    "
            f"{l2_misses}"
        )
        lines.append(
            f"board.cache_hierarchy.ruby_system."
            f"m_missLatencyHistSeqr::mean                "
            f"{avg_miss_lat}"
        )
        lines.append(
            f"system.mem_ctrl.readReqs                                 "
            f"{mem_reads}"
        )
        lines.append(
            f"system.mem_ctrl.writeReqs                                "
            f"{mem_writes}"
        )
        lines.append(
            f"---------- End Simulation Statistics ----------"
        )
        lines.append("")

    with open(os.path.join(config_dir, 'stats.txt'), 'w') as fp:
        fp.write('\n'.join(lines))


def main():
    output_dir = '/app/sim_output'
    os.makedirs(output_dir, exist_ok=True)

    count = 0
    for w in WIDTHS:
        for r in ROBS:
            for i in INTS:
                for f in FPS:
                    config_id = f"w{w}_r{r}_i{i}_f{f}"
                    generate_stats_file(config_id, w, r, i, f, output_dir)
                    count += 1

    # Generate calibration data using correct power model
    cal_configs = [
        (4, 32, 64, 64),
        (8, 128, 128, 128),
        (12, 256, 256, 256),
        (4, 256, 256, 256),
    ]

    with open('/app/calibration.csv', 'w') as fp:
        fp.write("config_id,measured_total_power\n")
        for w, r, i, f in cal_configs:
            cid = f"w{w}_r{r}_i{i}_f{f}"
            ipcs = []
            miss_rates = []
            for wl in WORKLOADS:
                ipc_val = ipc_model(w, r, i, f, wl)
                cycles = int(round(INST_COUNTS[wl] / ipc_val))
                ipcs.append(INST_COUNTS[wl] / cycles)

                l1_rate = l1_miss_rate_model(w, r, wl)
                l1_total = L1D_ACCESS_COUNTS[wl]
                l1_m = int(round(l1_total * l1_rate))
                miss_rates.append(l1_m / l1_total)

            product = 1.0
            for v in ipcs:
                product *= v
            avg_ipc = product ** (1.0 / len(ipcs))
            avg_miss = sum(miss_rates) / len(miss_rates)

            power = compute_power_correct(w, r, i, f, avg_ipc, avg_miss, 350)
            fp.write(f"{cid},{power}\n")

    print(f"Generated {count} configuration directories in {output_dir}")
    print(f"Generated calibration data at /app/calibration.csv")


if __name__ == '__main__':
    main()
