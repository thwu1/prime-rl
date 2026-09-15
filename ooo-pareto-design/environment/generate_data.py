#!/usr/bin/env python3
"""Generate synthetic OoO processor performance data.

The IPC model captures realistic bottleneck patterns:
- BFS: memory-bound, limited by ROB size (memory-level parallelism)
- Bubble Sort: branch-heavy, limited by pipeline width (low ILP)
- Matrix Multiply: compute/FP-bound, limited by FP register file
- N-Queens: recursive backtracking, limited by integer register file
"""
import math
import csv
import os

def ipc_model(w, r, i, f, workload):
    """Compute IPC using a min-of-ceilings model.

    Each parameter provides a ceiling on achievable IPC (logarithmic scaling).
    The actual IPC is the minimum across all resource ceilings.
    """
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


def main():
    widths = [4, 8, 12]
    robs = [32, 64, 128, 256]
    ints = [64, 128, 256]
    fps = [64, 128, 256]
    workloads = ['bfs', 'bubble_sort', 'matrix_multiply', 'nqueens']

    os.makedirs('/app', exist_ok=True)

    with open('/app/performance_data.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'config_id', 'width', 'rob_size',
            'num_int_regs', 'num_fp_regs', 'workload', 'ipc'
        ])
        for w in widths:
            for r in robs:
                for i in ints:
                    for fp in fps:
                        config_id = f"w{w}_r{r}_i{i}_f{fp}"
                        for wl in workloads:
                            ipc = ipc_model(w, r, i, fp, wl)
                            writer.writerow([config_id, w, r, i, fp, wl, ipc])


if __name__ == '__main__':
    main()
