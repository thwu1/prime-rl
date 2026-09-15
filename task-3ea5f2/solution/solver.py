#!/usr/bin/env python3
"""Solution: SPARTA ATS-5 Benchmark Forensics & Scaling Analysis.

Audits SPARTA log files for data quality issues, debugs the provided reference
awk/shell/bc FOM pipeline, computes corrected FOMs, fits and compares two
scaling models, stores results in SQLite, generates gnuplot visualizations,
and produces a comprehensive report.
"""


import json
import math
import os
import sqlite3
import subprocess

RANKS_PER_NODE = 112
LOG_DIR = "/app/data/logs"
MANIFEST_PATH = "/app/data/manifest.json"
RESULTS_FILE = "/app/report.json"
DB_PATH = "/app/benchmark.db"
SCHEMA_PATH = "/app/reference/schema.sql"

SCALING_RUNS = ["scaling_1", "scaling_4", "scaling_16", "scaling_64"]
NODE_COUNTS = {"scaling_1": 1, "scaling_4": 4, "scaling_16": 16, "scaling_64": 64}
ALL_RUNS = SCALING_RUNS + ["validation"]


def parse_sparta_log(filepath):
    """Parse SPARTA log file handling multiple stats blocks (restarts).

    Returns info dict and rows from the last valid block (wall_time >= 600).
    """
    info = {}
    all_blocks = []
    current_block = []
    in_block = False

    with open(filepath) as f:
        for raw_line in f:
            line = raw_line.strip()
            if "Running on" in line and "MPI task(s)" in line:
                parts = line.split()
                info["num_ranks"] = int(parts[2])
            if ("Step" in line and "CPU" in line and "Np" in line
                    and "Natt" in line and "Ncoll" in line
                    and "Maxlevel" in line):
                in_block = True
                current_block = []
                continue
            if "Loop time of" in line and "steps with" in line:
                in_block = False
                parts = line.split()
                block_info = {
                    "wall_time": float(parts[3]),
                    "total_steps": int(parts[8]),
                    "rows": current_block[:],
                }
                all_blocks.append(block_info)
                current_block = []
                continue
            if in_block:
                parts = line.split()
                if len(parts) == 6:
                    try:
                        current_block.append({
                            "step": int(parts[0]),
                            "cpu": float(parts[1]),
                            "np": int(parts[2]),
                            "natt": int(parts[3]),
                            "ncoll": int(parts[4]),
                            "maxlevel": int(parts[5]),
                        })
                    except (ValueError, IndexError):
                        pass

    info["num_nodes"] = round(info["num_ranks"] / RANKS_PER_NODE)
    info["num_blocks"] = len(all_blocks)

    valid_blocks = [b for b in all_blocks if b["wall_time"] >= 600.0]
    if valid_blocks:
        best = valid_blocks[-1]
        info["wall_time"] = best["wall_time"]
        return info, best["rows"]
    if all_blocks:
        info["wall_time"] = all_blocks[-1]["wall_time"]
        return info, all_blocks[-1]["rows"]
    return info, []


def compute_fom(info, rows):
    """Compute ATS-5 FOM with correct strict boundaries (300 < cpu < 600)."""
    reciprocals = []
    for row in rows:
        if row["cpu"] >= 600.0:
            break
        if row["cpu"] > 300.0:
            qoi = row["step"] * row["np"] / row["cpu"] / 1e6
            if qoi > 0:
                reciprocals.append(1.0 / qoi)
    if not reciprocals:
        return None
    hmean = len(reciprocals) / sum(reciprocals)
    return hmean / info["num_nodes"]


def audit_data(manifest):
    """Audit log files against manifest for data quality issues."""
    data_issues = []
    script_issues = []
    for run_name in ALL_RUNS:
        log_path = os.path.join(LOG_DIR, "{}.log".format(run_name))
        info, _ = parse_sparta_log(log_path)
        if info.get("num_blocks", 1) > 1:
            data_issues.append({
                "run": run_name,
                "issue_type": "restart",
                "detail": "Log contains {} statistics blocks (restart detected). "
                          "The reference awk pipeline exits on the first Loop "
                          "time line, using only the aborted block.".format(
                              info["num_blocks"]),
            })
        manifest_run = manifest["runs"].get(run_name, {})
        if manifest_run:
            expected_ranks = manifest_run.get("total_ranks")
            actual_ranks = info.get("num_ranks")
            if expected_ranks and actual_ranks and expected_ranks != actual_ranks:
                data_issues.append({
                    "run": run_name,
                    "issue_type": "manifest_mismatch",
                    "detail": "Manifest declares {} ranks ({} nodes) but log "
                              "shows {} ranks ({} nodes).".format(
                                  expected_ranks, manifest_run.get("nodes"),
                                  actual_ranks, info["num_nodes"]),
                })
    script_issues.append({
        "issue_type": "first_block_only",
        "detail": "Reference awk pipeline exits on first 'Loop time of' line, "
                  "failing on restart logs with multiple statistics blocks. "
                  "For scaling_16, this reads the aborted block with "
                  "wall_time < 600s, causing the script to error out.",
    })
    script_issues.append({
        "issue_type": "boundary_condition",
        "detail": "Reference awk uses 'cpu >= 300' instead of 'cpu > 300'. "
                  "ATS-5 spec requires strictly between 300 and 600 seconds.",
    })
    return data_issues, script_issues


def fit_power_law(nodes, foms):
    """Fit power-law model: FOM(p) = a * p^(-b) via log-log regression."""
    x = [math.log(n) for n in nodes]
    y = [math.log(f) for f in foms]
    n = len(x)
    x_mean = sum(x) / n
    y_mean = sum(y) / n
    sxx = sum((xi - x_mean) ** 2 for xi in x)
    sxy = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
    beta = sxy / sxx
    alpha = y_mean - beta * x_mean
    return math.exp(alpha), -beta


def fit_amdahl(nodes, foms):
    """Fit Amdahl's weak-scaling model via 1/FOM vs (p-1) regression."""
    x = [n - 1 for n in nodes]
    y = [1.0 / f for f in foms]
    n = len(x)
    x_mean = sum(x) / n
    y_mean = sum(y) / n
    sxx = sum((xi - x_mean) ** 2 for xi in x)
    sxy = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
    beta = sxy / sxx
    alpha = y_mean - beta * x_mean
    fom1 = 1.0 / alpha
    serial_fraction = beta * fom1
    return fom1, serial_fraction


def predict_power_law(p, coefficient, exponent):
    return coefficient * p ** (-exponent)


def predict_amdahl(p, fom1, serial_fraction):
    return fom1 / (1.0 + serial_fraction * (p - 1))


def r_squared_fom_space(nodes, actual_foms, predict_fn, *params):
    predicted = [predict_fn(n, *params) for n in nodes]
    mean_fom = sum(actual_foms) / len(actual_foms)
    ss_res = sum((a - p) ** 2 for a, p in zip(actual_foms, predicted))
    ss_tot = sum((a - mean_fom) ** 2 for a in actual_foms)
    if ss_tot == 0:
        return 1.0
    return 1.0 - ss_res / ss_tot


def populate_database(manifest, fom_results, run_infos,
                      am_f, am_fom1, am_r2, am_pred_256,
                      pl_exp, pl_coeff, pl_r2, pl_pred_256,
                      data_issues, script_issues):
    """Populate SQLite database with all benchmark results."""
    db = sqlite3.connect(DB_PATH)
    with open(SCHEMA_PATH) as f:
        db.executescript(f.read())

    for name in ALL_RUNS:
        info = run_infos[name]
        manifest_run = manifest["runs"].get(name, {})
        db.execute(
            "INSERT OR REPLACE INTO runs "
            "(run_name, num_nodes, num_ranks, wall_time, num_stats_blocks, "
            "fom, manifest_nodes, manifest_ranks) VALUES (?,?,?,?,?,?,?,?)",
            (name, info["num_nodes"], info["num_ranks"],
             info.get("wall_time"), info.get("num_blocks", 1),
             fom_results[name],
             manifest_run.get("nodes"), manifest_run.get("total_ranks"))
        )

    db.execute(
        "INSERT OR REPLACE INTO scaling_models VALUES (?,?,?,?,?,?,?)",
        ("amdahl", "serial_fraction", am_f,
         "fom1", am_fom1, am_r2, am_pred_256)
    )
    db.execute(
        "INSERT OR REPLACE INTO scaling_models VALUES (?,?,?,?,?,?,?)",
        ("power_law", "exponent", pl_exp,
         "coefficient", pl_coeff, pl_r2, pl_pred_256)
    )

    for issue in data_issues:
        db.execute(
            "INSERT INTO audit_issues "
            "(run_name, issue_type, category, detail) VALUES (?,?,?,?)",
            (issue["run"], issue["issue_type"], "data", issue["detail"])
        )
    for issue in script_issues:
        db.execute(
            "INSERT INTO audit_issues "
            "(run_name, issue_type, category, detail) VALUES (?,?,?,?)",
            (None, issue["issue_type"], "script", issue["detail"])
        )

    db.commit()
    db.close()
    print("SQLite database written to {}".format(DB_PATH))


def generate_gnuplot(fom_results, am_fom1, am_f, am_r2,
                     pl_coeff, pl_exp, pl_r2):
    """Generate gnuplot data files and produce scaling plot."""
    # Write measured data points
    with open("/app/scaling_data.dat", "w") as f:
        f.write("# nodes fom\n")
        for name in SCALING_RUNS:
            f.write("{} {:.8f}\n".format(NODE_COUNTS[name], fom_results[name]))

    # Generate smooth model curves for plotting
    curve_nodes = [1, 2, 4, 8, 16, 24, 32, 48, 64, 96, 128, 192, 256]
    with open("/app/amdahl_fit.dat", "w") as f:
        f.write("# nodes predicted_fom\n")
        for p in curve_nodes:
            f.write("{} {:.8f}\n".format(
                p, predict_amdahl(p, am_fom1, am_f)))

    with open("/app/powerlaw_fit.dat", "w") as f:
        f.write("# nodes predicted_fom\n")
        for p in curve_nodes:
            f.write("{} {:.8f}\n".format(
                p, predict_power_law(p, pl_coeff, pl_exp)))

    # Write gnuplot script
    gp_lines = [
        'set terminal png size 1024,768 font "Arial,12"',
        'set output "/app/scaling_plot.png"',
        'set title "SPARTA ATS-5 Weak Scaling - Per-Node FOM"',
        'set xlabel "Number of Compute Nodes"',
        'set ylabel "FOM (M-particle-steps/sec/node)"',
        'set logscale x 2',
        'set logscale y',
        'set grid xtics ytics',
        'set key top right box',
        'plot "/app/scaling_data.dat" using 1:2 with linespoints '
        'lt 1 lw 2 pt 7 ps 1.5 title "Measured FOM", \\',
        '     "/app/amdahl_fit.dat" using 1:2 with lines '
        'lt 2 lw 2 title "Amdahl (R2={:.4f})", \\'.format(am_r2),
        '     "/app/powerlaw_fit.dat" using 1:2 with lines '
        'lt 3 lw 2 title "Power-Law (R2={:.4f})"'.format(pl_r2),
    ]
    gp_script = "\n".join(gp_lines) + "\n"

    with open("/app/plot_cmd.gp", "w") as f:
        f.write(gp_script)

    subprocess.run(["gnuplot", "/app/plot_cmd.gp"], check=True)
    print("Scaling plot written to /app/scaling_plot.png")


def main():
    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    # 1. Audit
    data_issues, script_issues = audit_data(manifest)

    # 2. Compute corrected FOMs
    fom_results = {}
    run_infos = {}
    for name in ALL_RUNS:
        log_path = os.path.join(LOG_DIR, "{}.log".format(name))
        info, rows = parse_sparta_log(log_path)
        fom = compute_fom(info, rows)
        fom_results[name] = round(fom, 6) if fom else 0.0
        run_infos[name] = info

    # 3. Fit scaling models
    nodes = [NODE_COUNTS[n] for n in SCALING_RUNS]
    foms = [fom_results[n] for n in SCALING_RUNS]

    pl_coeff, pl_exp = fit_power_law(nodes, foms)
    pl_r2 = r_squared_fom_space(
        nodes, foms, predict_power_law, pl_coeff, pl_exp)
    pl_pred_256 = predict_power_law(256, pl_coeff, pl_exp)

    am_fom1, am_f = fit_amdahl(nodes, foms)
    am_r2 = r_squared_fom_space(
        nodes, foms, predict_amdahl, am_fom1, am_f)
    am_pred_256 = predict_amdahl(256, am_fom1, am_f)

    best_model = "power_law" if pl_r2 > am_r2 else "amdahl"

    # 4. Cross-validation
    actual_node_count = run_infos["validation"]["num_nodes"]
    actual_fom = fom_results["validation"]

    if best_model == "power_law":
        predicted_fom = predict_power_law(
            actual_node_count, pl_coeff, pl_exp)
    else:
        predicted_fom = predict_amdahl(
            actual_node_count, am_fom1, am_f)

    prediction_error_pct = abs(predicted_fom - actual_fom) / actual_fom * 100

    # 5. Generate gnuplot scaling visualization
    generate_gnuplot(fom_results, am_fom1, am_f, am_r2,
                     pl_coeff, pl_exp, pl_r2)

    # 6. Populate SQLite database
    populate_database(manifest, fom_results, run_infos,
                      am_f, am_fom1, am_r2, am_pred_256,
                      pl_exp, pl_coeff, pl_r2, pl_pred_256,
                      data_issues, script_issues)

    # 7. Build and write report.json
    report = {
        "audit": {
            "data_issues": data_issues,
            "script_issues": script_issues,
        },
        "fom": fom_results,
        "scaling_models": {
            "amdahl": {
                "serial_fraction": round(am_f, 8),
                "r_squared": round(am_r2, 6),
                "predicted_fom_256": round(am_pred_256, 6),
            },
            "power_law": {
                "exponent": round(pl_exp, 8),
                "coefficient": round(pl_coeff, 6),
                "r_squared": round(pl_r2, 6),
                "predicted_fom_256": round(pl_pred_256, 6),
            },
            "best_model": best_model,
        },
        "cross_validation": {
            "actual_node_count": actual_node_count,
            "predicted_fom": round(predicted_fom, 6),
            "actual_fom": round(actual_fom, 6),
            "prediction_error_pct": round(prediction_error_pct, 4),
        },
    }

    with open(RESULTS_FILE, "w") as f:
        json.dump(report, f, indent=2)

    print("Report written to {}".format(RESULTS_FILE))


if __name__ == "__main__":
    main()
