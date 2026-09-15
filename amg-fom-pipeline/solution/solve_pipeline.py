#!/usr/bin/env python3
"""HPC Procurement Benchmark Audit Pipeline."""
import sqlite3
import json
import math
import os
import tomllib
from statistics import median, mean, stdev
from datetime import datetime
from collections import defaultdict

DB_PATH = "/app/benchmark.db"
CONFIG_PATH = "/app/config.toml"
STD_CONFIGS_PATH = "/app/docs/standard_configs.toml"
RESULTS_DIR = "/app/results"

# t-distribution critical values (two-tailed, alpha=0.05) for small df
T_CRIT_95 = {
    4: 2.7764, 5: 2.5706, 6: 2.4469, 7: 2.3646,
    8: 2.3060, 9: 2.2622, 10: 2.2281, 15: 2.1314, 20: 2.0860,
}


def load_toml(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def compute_fom(bench_name, meas_dict):
    """Compute FOM from raw measurement dict. Returns None if critical data missing."""
    m = meas_dict
    if bench_name == "amg":
        vals = [m.get("nnz"), m.get("iterations"), m.get("solve_time")]
        if any(v is None for v in vals):
            return None
        return m["nnz"] * m["iterations"] / m["solve_time"]
    elif bench_name == "kripke":
        keys = ["zones", "directions", "groups", "iterations", "sweep_time"]
        vals = [m.get(k) for k in keys]
        if any(v is None for v in vals):
            return None
        return m["zones"] * m["directions"] * m["groups"] * m["iterations"] / m["sweep_time"]
    elif bench_name == "stream":
        v = m.get("triad_bandwidth")
        return v if v is not None else None
    elif bench_name == "pennant":
        keys = ["zones", "cycles", "elapsed_time"]
        vals = [m.get(k) for k in keys]
        if any(v is None for v in vals):
            return None
        return m["zones"] * m["cycles"] / m["elapsed_time"]
    return None


def get_t_crit(df):
    if df in T_CRIT_95:
        return T_CRIT_95[df]
    # Approximate for larger df
    return 1.96 + 2.4 / df


def main():
    config = load_toml(CONFIG_PATH)
    std_cfg = load_toml(STD_CONFIGS_PATH)
    weights = config["weights"]
    scoring = config["scoring"]
    quality_cfg = config["quality"]
    ref_system = scoring["reference_system"]
    min_interval = quality_cfg["min_run_interval_seconds"]
    min_valid = quality_cfg["min_valid_runs"]
    min_distinct = quality_cfg["min_distinct_fom_values"]

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Load lookups
    systems = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM systems")}
    benchmarks = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM benchmarks")}
    total_runs = conn.execute("SELECT COUNT(*) AS c FROM runs").fetchone()["c"]

    # Fetch all runs grouped by (system, benchmark)
    all_runs = conn.execute("""
        SELECT id, system_id, benchmark_id, run_number, status, timestamp, reported_fom
        FROM runs ORDER BY system_id, benchmark_id, run_number
    """).fetchall()

    sb_runs = defaultdict(list)
    for r in all_runs:
        sn = systems[r["system_id"]]
        bn = benchmarks[r["benchmark_id"]]
        sb_runs[(sn, bn)].append(dict(r))

    # ── Phase 1: Detect timing anomalies ──
    timing_anomaly_ids = set()
    for (sn, bn), runs in sb_runs.items():
        valid = [r for r in runs if r["status"] != "ERROR"]
        valid.sort(key=lambda r: r["timestamp"])
        for i in range(1, len(valid)):
            t1 = datetime.fromisoformat(valid[i - 1]["timestamp"])
            t2 = datetime.fromisoformat(valid[i]["timestamp"])
            gap = abs((t2 - t1).total_seconds())
            if gap < min_interval:
                timing_anomaly_ids.add(valid[i - 1]["id"])
                timing_anomaly_ids.add(valid[i]["id"])

    # ── Phase 2: Process runs, compute FOMs, detect discrepancies ──
    excluded_runs = []
    fom_discrepancies = []
    valid_foms = defaultdict(lambda: defaultdict(list))

    for r in all_runs:
        rid = r["id"]
        sn = systems[r["system_id"]]
        bn = benchmarks[r["benchmark_id"]]

        if r["status"] == "ERROR":
            excluded_runs.append({"run_id": rid, "reason": "error_status"})
            continue

        if rid in timing_anomaly_ids:
            excluded_runs.append({"run_id": rid, "reason": "timing_anomaly"})
            continue

        # Get measurements
        meas_rows = conn.execute(
            "SELECT metric_name, metric_value FROM measurements WHERE run_id = ?",
            (rid,)).fetchall()
        meas = {row["metric_name"]: row["metric_value"] for row in meas_rows}

        computed = compute_fom(bn, meas)
        if computed is None:
            excluded_runs.append({"run_id": rid, "reason": "null_measurement"})
            continue

        # Check FOM discrepancy
        reported = r["reported_fom"]
        if reported is not None:
            pct_err = (reported - computed) / computed * 100.0
            if abs(pct_err) > 1.0:
                fom_discrepancies.append({
                    "run_id": rid,
                    "reported_fom": round(reported, 4),
                    "computed_fom": round(computed, 4),
                    "pct_error": round(pct_err, 2),
                })

        valid_foms[sn][bn].append(computed)

    # ── Phase 3: Quality flags ──
    quality_flags = []

    # 3a: Configuration mismatch (check run_config against standard)
    config_checks = {
        "amg": [("grid_nx", "grid_nx"), ("grid_ny", "grid_ny"), ("grid_nz", "grid_nz")],
        "kripke": [("zones_x", "zones_x"), ("num_directions", "num_directions"),
                   ("num_groups", "num_groups")],
        "stream": [("array_size", "array_size")],
        "pennant": [("mesh_type", "mesh_type"), ("mesh_scale", "mesh_scale")],
    }
    for (sn, bn), runs in sb_runs.items():
        if bn not in config_checks:
            continue
        std = std_cfg.get(bn, {})
        for r in runs:
            if r["status"] == "ERROR" or r["id"] in timing_anomaly_ids:
                continue
            cfgs = conn.execute(
                "SELECT param_name, param_value FROM run_config WHERE run_id = ?",
                (r["id"],)).fetchall()
            cd = {c["param_name"]: c["param_value"] for c in cfgs}
            mismatches = []
            for db_key, std_key in config_checks[bn]:
                db_val = cd.get(db_key)
                std_val = std.get(std_key)
                if db_val is not None and std_val is not None:
                    if str(db_val) != str(std_val):
                        mismatches.append(f"{db_key}={db_val} (expected {std_val})")
            if mismatches:
                quality_flags.append({
                    "system": sn, "benchmark": bn,
                    "flag": "configuration_mismatch",
                    "details": "Non-standard config: " + ", ".join(mismatches),
                })
                break

    # 3b: Insufficient variance (min distinct FOM values)
    for sn in systems.values():
        for bn in benchmarks.values():
            foms = valid_foms[sn][bn]
            if len(foms) == 0:
                continue
            distinct = len(set(round(f, 2) for f in foms))
            if distinct < min_distinct:
                quality_flags.append({
                    "system": sn, "benchmark": bn,
                    "flag": "insufficient_variance",
                    "details": f"Only {distinct} distinct FOM value(s) across "
                               f"{len(foms)} runs (minimum required: {min_distinct})",
                })

    # 3c: Timing anomaly flag at system-benchmark level
    for (sn, bn), runs in sb_runs.items():
        cnt = sum(1 for r in runs if r["id"] in timing_anomaly_ids)
        if cnt > 0:
            quality_flags.append({
                "system": sn, "benchmark": bn,
                "flag": "timing_anomaly",
                "details": f"{cnt} runs with timestamps closer than "
                           f"{min_interval}s apart",
            })

    # ── Phase 4: Performance summary ──
    flagged_map = defaultdict(list)
    for f in quality_flags:
        flagged_map[f["system"]].append(f"{f['benchmark']}: {f['flag']}")

    perf_summary = {}
    for sn in systems.values():
        perf_summary[sn] = {}
        for bn in benchmarks.values():
            foms = valid_foms[sn][bn]
            n = len(foms)
            is_flagged = any(
                f["system"] == sn and f["benchmark"] == bn
                for f in quality_flags
            )
            if n == 0:
                perf_summary[sn][bn] = {
                    "median_fom": None, "mean_fom": None, "std_fom": None,
                    "ci_lower": None, "ci_upper": None,
                    "valid_run_count": 0, "flagged": is_flagged,
                }
                continue

            med = median(foms)
            avg = mean(foms)
            sd = stdev(foms) if n > 1 else 0.0
            if n > 1 and sd > 0:
                t_val = get_t_crit(n - 1)
                margin = t_val * sd / math.sqrt(n)
                ci_lo, ci_hi = avg - margin, avg + margin
            else:
                ci_lo, ci_hi = avg, avg

            perf_summary[sn][bn] = {
                "median_fom": round(med, 4),
                "mean_fom": round(avg, 4),
                "std_fom": round(sd, 4),
                "ci_lower": round(ci_lo, 4),
                "ci_upper": round(ci_hi, 4),
                "valid_run_count": n,
                "flagged": is_flagged,
            }

    # ── Phase 5: Ranking (weighted geometric mean with reference normalization) ──
    bench_list = list(benchmarks.values())
    ref_medians = {b: perf_summary[ref_system][b]["median_fom"] for b in bench_list}

    rankings = []
    for sn in systems.values():
        score = 1.0
        for b in bench_list:
            med = perf_summary[sn][b]["median_fom"]
            ref_m = ref_medians[b]
            if med is None or ref_m is None or ref_m == 0:
                score = 0.0
                break
            normalized = med / ref_m
            score *= normalized ** weights[b]
        rankings.append({
            "system": sn,
            "score": round(score, 6),
            "flags": flagged_map.get(sn, []),
        })

    rankings.sort(key=lambda x: x["score"], reverse=True)
    for i, r in enumerate(rankings):
        r["rank"] = i + 1

    # ── Phase 6: Efficiency Analysis ──
    # Get theoretical peak bandwidth for each system from STREAM measurements
    sys_name_to_id = {v: k for k, v in systems.items()}
    stream_bid = [k for k, v in benchmarks.items() if v == "stream"][0]

    peak_bw = {}
    for sn, sid in sys_name_to_id.items():
        row = conn.execute("""
            SELECT m.metric_value FROM measurements m
            JOIN runs r ON m.run_id = r.id
            WHERE r.system_id = ? AND r.benchmark_id = ?
            AND m.metric_name = 'theoretical_peak' AND m.metric_value IS NOT NULL
            LIMIT 1
        """, (sid, stream_bid)).fetchone()
        if row:
            peak_bw[sn] = row[0]

    # STREAM efficiency: measured_triad / theoretical_peak
    stream_eff = {}
    for sn in systems.values():
        triad_med = perf_summary[sn]["stream"]["median_fom"]
        peak = peak_bw.get(sn)
        if triad_med is not None and peak is not None and peak > 0:
            eff = triad_med / peak
            stream_eff[sn] = {
                "measured_bandwidth": round(triad_med, 4),
                "theoretical_peak": round(peak, 4),
                "efficiency": round(eff, 4)
            }

    # Cross-benchmark analysis: AMG FOM / STREAM bandwidth ratio
    amg_ratios_raw = {}
    for sn in systems.values():
        amg_med = perf_summary[sn]["amg"]["median_fom"]
        stream_med = perf_summary[sn]["stream"]["median_fom"]
        if amg_med is not None and stream_med is not None and stream_med > 0:
            amg_ratios_raw[sn] = amg_med / stream_med

    ratio_values = list(amg_ratios_raw.values())
    fleet_mean_r = mean(ratio_values)
    fleet_std_r = stdev(ratio_values) if len(ratio_values) > 1 else 0.0
    eff_threshold = config["efficiency"]["outlier_sigma_threshold"]

    outliers = sorted([
        sn for sn, ratio in amg_ratios_raw.items()
        if fleet_std_r > 0 and abs(ratio - fleet_mean_r) > eff_threshold * fleet_std_r
    ])

    efficiency_result = {
        "stream_efficiency": stream_eff,
        "cross_benchmark_analysis": {
            "amg_bandwidth_ratios": {sn: round(r, 2) for sn, r in amg_ratios_raw.items()},
            "fleet_mean": round(fleet_mean_r, 2),
            "fleet_std": round(fleet_std_r, 2),
            "outlier_threshold_sigma": eff_threshold,
            "outliers": outliers
        }
    }

    # ── Write outputs ──
    os.makedirs(RESULTS_DIR, exist_ok=True)

    audit_report = {
        "total_runs": total_runs,
        "excluded_runs": excluded_runs,
        "quality_flags": quality_flags,
        "fom_discrepancies": fom_discrepancies,
    }
    for name, data in [("audit_report.json", audit_report),
                       ("performance_summary.json", perf_summary),
                       ("efficiency_analysis.json", efficiency_result),
                       ("ranking.json", {"rankings": rankings})]:
        with open(os.path.join(RESULTS_DIR, name), "w") as f:
            json.dump(data, f, indent=2)

    conn.close()
    print(f"Audit complete. Results in {RESULTS_DIR}")


if __name__ == "__main__":
    main()
