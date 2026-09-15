#!/usr/bin/env python3
"""Create the perf.db SQLite database with OoO processor simulation data.

This script generates synthetic IPC measurements for 108 processor
configurations across 4 workloads using a min-of-ceilings model that
captures realistic microarchitectural bottleneck patterns.
"""
import sqlite3
import math


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
    conn = sqlite3.connect('/app/perf.db')
    c = conn.cursor()

    c.execute('''CREATE TABLE configurations (
        config_id TEXT PRIMARY KEY,
        width INTEGER NOT NULL,
        rob_size INTEGER NOT NULL,
        num_int_regs INTEGER NOT NULL,
        num_fp_regs INTEGER NOT NULL
    )''')

    c.execute('''CREATE TABLE workloads (
        name TEXT PRIMARY KEY,
        description TEXT NOT NULL
    )''')

    c.execute('''CREATE TABLE measurements (
        config_id TEXT NOT NULL,
        workload TEXT NOT NULL,
        ipc REAL NOT NULL,
        PRIMARY KEY (config_id, workload),
        FOREIGN KEY (config_id) REFERENCES configurations(config_id),
        FOREIGN KEY (workload) REFERENCES workloads(name)
    )''')

    c.execute('''CREATE TABLE metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )''')

    workload_info = [
        ('bfs', 'Breadth-First Search: memory-intensive, irregular access patterns'),
        ('bubble_sort', 'Bubble Sort: branch-heavy, low instruction-level parallelism'),
        ('matrix_multiply', 'Matrix Multiplication: compute-intensive, FP-heavy'),
        ('nqueens', 'N-Queens solver: recursive backtracking, integer-heavy'),
    ]
    c.executemany('INSERT INTO workloads VALUES (?, ?)', workload_info)

    c.execute("INSERT INTO metadata VALUES ('baseline_config', 'w4_r32_i64_f64')")
    c.execute("INSERT INTO metadata VALUES ('budget_levels', '1500,3000,5000,8000')")

    widths = [4, 8, 12]
    robs = [32, 64, 128, 256]
    ints = [64, 128, 256]
    fps = [64, 128, 256]

    for w in widths:
        for r in robs:
            for i in ints:
                for fp in fps:
                    config_id = f"w{w}_r{r}_i{i}_f{fp}"
                    c.execute(
                        'INSERT INTO configurations VALUES (?, ?, ?, ?, ?)',
                        (config_id, w, r, i, fp)
                    )
                    for wl_name, _ in workload_info:
                        ipc = ipc_model(w, r, i, fp, wl_name)
                        c.execute(
                            'INSERT INTO measurements VALUES (?, ?, ?)',
                            (config_id, wl_name, ipc)
                        )

    conn.commit()
    conn.close()
    print("Database created at /app/perf.db")


if __name__ == '__main__':
    main()
