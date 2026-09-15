#!/usr/bin/env python3
"""Generate synthetic ERT benchmark data with known system parameters.

Produces raw ERT-style output files with realistic cache-level bandwidth
plateaus and noise for a simulated multi-core HPC node.
"""

import os
import random
import math

# System parameters (ground truth)
L1_SIZE = 32768       # 32 KB
L2_SIZE = 262144      # 256 KB
L3_SIZE = 8388608     # 8 MB

L1_BW = 1450.0   # GB/s
L2_BW = 480.0    # GB/s
L3_BW = 190.0    # GB/s
DRAM_BW = 72.0   # GB/s

PEAK_GFLOPS = 280.0  # GFLOPs/s

ELEMENT_SIZE = 8  # bytes (double precision)
MEM_ACCESSES = 2  # 1 read + 1 write per element (ERT convention)

FLOP_COUNTS = [1, 2, 4, 8, 16, 32, 64]

random.seed(42)


def get_bandwidth(ws_bytes):
    """Get effective bandwidth for a given working set size with sigmoid transitions."""
    transitions = [
        (L1_SIZE, L1_BW, L2_BW),
        (L2_SIZE, L2_BW, L3_BW),
        (L3_SIZE, L3_BW, DRAM_BW),
    ]

    # Check if in a transition region
    for boundary, bw_high, bw_low in transitions:
        lower = boundary * 0.7
        upper = boundary * 2.0
        if lower < ws_bytes <= upper:
            log_ratio = math.log(ws_bytes / boundary) / math.log(2.0)
            t = 1.0 / (1.0 + math.exp(-5.0 * log_ratio))
            base_bw = bw_high * (1.0 - t) + bw_low * t
            noise = random.gauss(0, 0.015)
            return max(base_bw * (1.0 + noise), 1.0)

    # Not in transition; determine plateau
    if ws_bytes <= L1_SIZE * 0.7:
        base_bw = L1_BW
    elif ws_bytes <= L2_SIZE * 0.7:
        base_bw = L2_BW
    elif ws_bytes <= L3_SIZE * 0.7:
        base_bw = L3_BW
    else:
        base_bw = DRAM_BW

    noise = random.gauss(0, 0.015)
    return max(base_bw * (1.0 + noise), 1.0)


def generate_ert_data():
    """Generate raw ERT-style benchmark data files."""
    os.makedirs("/app/data", exist_ok=True)

    # Working set sizes: from 64 elements to ~15M elements, multiply by ~1.3
    ws_sizes = []
    n = 64
    while n <= 16000000:
        ws_sizes.append(n)
        next_n = max(n + 1, int(n * 1.3))
        n = next_n

    for ert_flops in FLOP_COUNTS:
        filename = "/app/data/flops_{:03d}.dat".format(ert_flops)
        ai = ert_flops / (MEM_ACCESSES * ELEMENT_SIZE)

        with open(filename, 'w') as f:
            f.write("# ERT raw output - FLOPS per element: {}\n".format(ert_flops))
            f.write("# Kernel: a[i] = a[i] * alpha + b[i] (with {} FP operations)\n".format(ert_flops))
            f.write("# Format: working_set_bytes trials microseconds total_bytes total_flops\n")
            f.write("#\n")

            for n_elements in ws_sizes:
                ws_bytes = n_elements * ELEMENT_SIZE

                trials = max(1, int(5000000 / n_elements))

                total_bytes = trials * n_elements * ELEMENT_SIZE * MEM_ACCESSES
                total_flops = trials * n_elements * ert_flops

                bw = get_bandwidth(ws_bytes)

                bw_limited_gflops = ai * bw
                peak_noisy = PEAK_GFLOPS * (1.0 + random.gauss(0, 0.015))

                actual_gflops = min(bw_limited_gflops, peak_noisy)

                time_sec = total_flops / (actual_gflops * 1e9)
                microseconds = time_sec * 1e6

                f.write("{:>15d} {:>10d} {:>18.3f} {:>18d} {:>18d}\n".format(
                    ws_bytes, trials, microseconds, total_bytes, total_flops))

    print("Generated {} data files in /app/data/".format(len(FLOP_COUNTS)))
    print("Working set sizes: {} points from {} to {} bytes".format(
        len(ws_sizes), ws_sizes[0] * 8, ws_sizes[-1] * 8))


if __name__ == "__main__":
    generate_ert_data()
