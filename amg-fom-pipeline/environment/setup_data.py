#!/usr/bin/env python3
"""Generate the CORAL-2 procurement benchmark SQLite database with embedded data quality issues."""
import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = "/app/benchmark.db"


def make_variations(base, n=8, pct=0.02):
    """Generate n values varying around base by +/- pct deterministically."""
    factors = [1.00, 1 + pct, 1 - pct, 1 + pct / 2, 1 - pct / 2,
               1 + pct * 1.5, 1 - pct * 1.5, 1.00]
    return [round(base * factors[i], 6) for i in range(n)]


def create_schema(conn):
    conn.executescript("""
        CREATE TABLE systems (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            vendor TEXT,
            node_count INTEGER,
            cores_per_node INTEGER,
            memory_gb_per_node REAL,
            accelerator TEXT
        );
        CREATE TABLE benchmarks (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            category TEXT,
            description TEXT
        );
        CREATE TABLE runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id INTEGER NOT NULL,
            benchmark_id INTEGER NOT NULL,
            run_number INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'PASS',
            timestamp TEXT NOT NULL,
            reported_fom REAL,
            FOREIGN KEY (system_id) REFERENCES systems(id),
            FOREIGN KEY (benchmark_id) REFERENCES benchmarks(id)
        );
        CREATE TABLE measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            metric_name TEXT NOT NULL,
            metric_value REAL,
            unit TEXT,
            FOREIGN KEY (run_id) REFERENCES runs(id)
        );
        CREATE TABLE run_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            param_name TEXT NOT NULL,
            param_value TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES runs(id)
        );
    """)


def populate_static(conn):
    systems = [
        (1, "Sierra-2", "IBM", 4320, 44, 256.0, "NVIDIA V100"),
        (2, "Frontier-X", "HPE", 9408, 64, 512.0, "AMD MI250X"),
        (3, "Aurora-1", "Intel", 10624, 52, 512.0, "Intel PVC"),
        (4, "Titan-X", "Cray", 5120, 48, 256.0, "NVIDIA A100"),
        (5, "Nova-7", "Dell", 3200, 96, 1024.0, "NVIDIA H100"),
        (6, "Pulsar-3", "Nvidia", 6144, 72, 384.0, "NVIDIA GH200"),
    ]
    conn.executemany("INSERT INTO systems VALUES (?,?,?,?,?,?,?)", systems)

    benchmarks = [
        (1, "amg", "throughput",
         "Algebraic multigrid solver for linear systems from unstructured grids"),
        (2, "kripke", "throughput",
         "Deterministic Sn transport sweep benchmark"),
        (3, "stream", "memory",
         "Memory bandwidth benchmark measuring sustained bandwidth"),
        (4, "pennant", "throughput",
         "Unstructured mesh hydrodynamics mini-app"),
    ]
    conn.executemany("INSERT INTO benchmarks VALUES (?,?,?,?)", benchmarks)


def populate_runs(conn):
    base_time = datetime(2024, 6, 1, 9, 0, 0)

    # Performance baselines per system
    amg_base_st = {"Sierra-2": 2.80, "Frontier-X": 1.40, "Aurora-1": 1.80,
                   "Titan-X": 1.75, "Nova-7": 2.00, "Pulsar-3": 2.20}
    kripke_base_st = {"Sierra-2": 5.00, "Frontier-X": 2.00, "Aurora-1": 3.00,
                      "Titan-X": 2.50, "Nova-7": 4.00, "Pulsar-3": 3.50}
    stream_base_tr = {"Sierra-2": 135000.0, "Frontier-X": 310000.0,
                      "Aurora-1": 250000.0, "Titan-X": 192000.0,
                      "Nova-7": 220000.0, "Pulsar-3": 175000.0}
    stream_base_pk = {"Sierra-2": 160000.0, "Frontier-X": 400000.0,
                      "Aurora-1": 320000.0, "Titan-X": 240000.0,
                      "Nova-7": 280000.0, "Pulsar-3": 220000.0}
    pennant_base_el = {"Sierra-2": 8.00, "Frontier-X": 4.00, "Aurora-1": 5.00,
                       "Titan-X": 4.50, "Nova-7": 6.00, "Pulsar-3": 5.50}

    # Data quality issues
    error_runs = {
        ("Sierra-2", "stream", 2),
        ("Frontier-X", "amg", 4),
        ("Aurora-1", "kripke", 1),
        ("Titan-X", "pennant", 6),
        ("Nova-7", "amg", 3),
    }
    null_runs = {
        ("Pulsar-3", "amg", 5): "solve_time",
        ("Aurora-1", "stream", 7): "triad_bandwidth",
    }
    timing_anomaly_runs = {
        ("Pulsar-3", "pennant", 5),
        ("Pulsar-3", "pennant", 6),
        ("Pulsar-3", "pennant", 7),
    }

    sys_order = ["Sierra-2", "Frontier-X", "Aurora-1", "Titan-X", "Nova-7", "Pulsar-3"]
    sys_ids = {n: i + 1 for i, n in enumerate(sys_order)}
    bench_order = ["amg", "kripke", "stream", "pennant"]
    bench_ids = {n: i + 1 for i, n in enumerate(bench_order)}

    run_id = 0
    for sn in sys_order:
        sid = sys_ids[sn]
        for bn in bench_order:
            bid = bench_ids[bn]
            for rn in range(8):
                run_id += 1
                is_error = (sn, bn, rn) in error_runs
                null_metric = null_runs.get((sn, bn, rn))
                is_timing = (sn, bn, rn) in timing_anomaly_runs
                status = "ERROR" if is_error else "PASS"

                # Timestamp
                if is_timing:
                    ts = base_time + timedelta(
                        hours=(sid - 1) * 48 + (bid - 1) * 12 + 20,
                        seconds=(rn - 5) * 5)
                else:
                    ts = base_time + timedelta(
                        hours=(sid - 1) * 48 + (bid - 1) * 12 + rn * 2)
                timestamp = ts.isoformat()

                # --- AMG ---
                if bn == "amg":
                    actual_nnz = 3500000 if sn == "Titan-X" else 7000000
                    iters = 20
                    st = make_variations(amg_base_st[sn])[rn]
                    # BUG: Titan-X reported_fom uses nnz=7M regardless
                    rfom = (7000000 * iters / st) if not is_error else None
                    conn.execute(
                        "INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
                        (run_id, sid, bid, rn + 1, status, timestamp, rfom))
                    if not is_error:
                        st_val = None if null_metric == "solve_time" else st
                        for m in [("nnz", actual_nnz, "count"),
                                  ("iterations", iters, "count"),
                                  ("solve_time", st_val, "seconds"),
                                  ("setup_time", round(st * 0.4, 6), "seconds"),
                                  ("convergence_factor",
                                   0.135 if sn == "Titan-X" else 0.142, "ratio")]:
                            conn.execute(
                                "INSERT INTO measurements (run_id,metric_name,metric_value,unit) "
                                "VALUES (?,?,?,?)", (run_id, m[0], m[1], m[2]))
                        grid = "50" if sn == "Titan-X" else "100"
                        for c in [("grid_nx", grid), ("grid_ny", grid),
                                  ("grid_nz", grid), ("solver", "amg")]:
                            conn.execute(
                                "INSERT INTO run_config (run_id,param_name,param_value) "
                                "VALUES (?,?,?)", (run_id, c[0], c[1]))

                # --- Kripke ---
                elif bn == "kripke":
                    zones, dirs, groups, iters = 1000, 100, 10, 10
                    st = make_variations(kripke_base_st[sn])[rn]
                    # BUG: reported_fom omits iterations factor
                    rfom = (zones * dirs * groups / st) if not is_error else None
                    conn.execute(
                        "INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
                        (run_id, sid, bid, rn + 1, status, timestamp, rfom))
                    if not is_error:
                        for m in [("zones", zones, "count"),
                                  ("directions", dirs, "count"),
                                  ("groups", groups, "count"),
                                  ("iterations", iters, "count"),
                                  ("sweep_time", st, "seconds"),
                                  ("particles_per_zone", 10, "count"),
                                  ("particle_count", zones * 10, "count")]:
                            conn.execute(
                                "INSERT INTO measurements (run_id,metric_name,metric_value,unit) "
                                "VALUES (?,?,?,?)", (run_id, m[0], m[1], m[2]))
                        for c in [("nesting", "DGZ"), ("zones_x", "10"),
                                  ("zones_y", "10"), ("zones_z", "10"),
                                  ("num_directions", str(dirs)),
                                  ("num_groups", str(groups))]:
                            conn.execute(
                                "INSERT INTO run_config (run_id,param_name,param_value) "
                                "VALUES (?,?,?)", (run_id, c[0], c[1]))

                # --- STREAM ---
                elif bn == "stream":
                    if sn == "Nova-7":
                        triad = stream_base_tr[sn]  # identical for all runs
                    else:
                        triad = make_variations(stream_base_tr[sn])[rn]
                    copy_bw = round(triad * 1.02, 2)
                    scale_bw = round(triad * 1.01, 2)
                    add_bw = round(triad * 1.015, 2)
                    peak = stream_base_pk[sn]
                    rfom = triad if not is_error else None
                    conn.execute(
                        "INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
                        (run_id, sid, bid, rn + 1, status, timestamp, rfom))
                    if not is_error:
                        t_val = None if null_metric == "triad_bandwidth" else triad
                        for m in [("copy_bandwidth", copy_bw, "MB/s"),
                                  ("scale_bandwidth", scale_bw, "MB/s"),
                                  ("add_bandwidth", add_bw, "MB/s"),
                                  ("triad_bandwidth", t_val, "MB/s"),
                                  ("theoretical_peak", peak, "MB/s"),
                                  ("array_size", 80000000, "elements")]:
                            conn.execute(
                                "INSERT INTO measurements (run_id,metric_name,metric_value,unit) "
                                "VALUES (?,?,?,?)", (run_id, m[0], m[1], m[2]))
                        for c in [("array_size", "80000000"),
                                  ("num_threads", "1")]:
                            conn.execute(
                                "INSERT INTO run_config (run_id,param_name,param_value) "
                                "VALUES (?,?,?)", (run_id, c[0], c[1]))

                # --- PENNANT ---
                elif bn == "pennant":
                    zones, cycles = 65536, 100
                    el = make_variations(pennant_base_el[sn])[rn]
                    rfom = (zones * cycles / el) if not is_error else None
                    conn.execute(
                        "INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
                        (run_id, sid, bid, rn + 1, status, timestamp, rfom))
                    if not is_error:
                        for m in [("zones", zones, "count"),
                                  ("cycles", cycles, "count"),
                                  ("elapsed_time", el, "seconds"),
                                  ("zone_count_final", zones, "count")]:
                            conn.execute(
                                "INSERT INTO measurements (run_id,metric_name,metric_value,unit) "
                                "VALUES (?,?,?,?)", (run_id, m[0], m[1], m[2]))
                        for c in [("mesh_type", "noh"), ("mesh_scale", "4")]:
                            conn.execute(
                                "INSERT INTO run_config (run_id,param_name,param_value) "
                                "VALUES (?,?,?)", (run_id, c[0], c[1]))

    conn.commit()


def main():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    create_schema(conn)
    populate_static(conn)
    populate_runs(conn)
    total = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    meas = conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
    conn.close()
    print(f"Created {DB_PATH}: {total} runs, {meas} measurements")


if __name__ == "__main__":
    main()
