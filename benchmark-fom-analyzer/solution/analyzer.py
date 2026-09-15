#!/usr/bin/env python3
"""
HPC Benchmark Procurement Evaluation Pipeline
Multi-tool pipeline: Python + AWK + SQLite + JSON Schema

"""

import json
import math
import os
import re
import sqlite3
import subprocess
import tomllib


def load_toml(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


# ---------------------------------------------------------------------------
# LAMMPS parser
# ---------------------------------------------------------------------------

def parse_lammps_log(path):
    with open(path) as f:
        text = f.read()

    loop_match = re.search(
        r"Loop time of ([\d.]+) on (\d+) procs for (\d+) steps with (\d+) atoms",
        text,
    )
    wall_time = float(loop_match.group(1))
    num_timesteps = int(loop_match.group(3))
    num_atoms = int(loop_match.group(4))

    header_match = re.search(
        r"^(Step\s+Temp\s+PotEng\s+TotEng\s+Press\s+Volume)",
        text, re.MULTILINE,
    )
    header_pos = header_match.end()
    remaining = text[header_pos:]
    thermo_data = []
    for line in remaining.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 4:
            try:
                step = int(parts[0])
                pot_eng = float(parts[2])
                thermo_data.append((step, pot_eng))
            except (ValueError, IndexError):
                break

    return {
        "num_atoms": num_atoms,
        "num_timesteps": num_timesteps,
        "wall_time": wall_time,
        "thermo": thermo_data,
    }


def compute_lammps_fom(parsed):
    return (parsed["num_atoms"] * parsed["num_timesteps"]) / parsed["wall_time"]


def validate_lammps(parsed, spec):
    val_spec = spec["benchmarks"]["lammps"]["validation"]
    atoms_per_mol = val_spec["atoms_per_molecule"]
    ref_value = val_spec["reference_value"]
    tolerance = val_spec["tolerance"]

    num_molecules = parsed["num_atoms"] / atoms_per_mol
    total_steps = parsed["num_timesteps"]
    half = total_steps / 2

    pe_values = [pe for step, pe in parsed["thermo"] if step >= half]
    if not pe_values:
        return False, 0.0

    avg_pe = sum(pe_values) / len(pe_values)
    pe_per_mol = avg_pe / num_molecules

    low = ref_value - tolerance
    high = ref_value + tolerance
    return (low <= pe_per_mol <= high), pe_per_mol


# ---------------------------------------------------------------------------
# MILC — uses AWK validation tool
# ---------------------------------------------------------------------------

def run_milc_awk_validation(log_path, spec, output_dir):
    """Invoke the AWK validation script on a MILC log file."""
    val_spec = spec["benchmarks"]["milc"]["validation"]
    traj_steps = spec["benchmarks"]["milc"]["trajectory_steps"]

    os.makedirs(output_dir, exist_ok=True)

    result = subprocess.run(
        [
            "awk", "-f", "/app/tools/validate_milc.awk",
            "-v", f"ref_plaq={val_spec['reference_value']}",
            "-v", f"tol_pct={val_spec['tolerance_percent']}",
            "-v", f"traj_steps={traj_steps}",
            log_path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    basename = os.path.basename(log_path)
    output_path = os.path.join(output_dir, f"{basename}.validation")
    with open(output_path, "w") as f:
        f.write(result.stdout)

    metrics = {}
    for line in result.stdout.strip().split("\n"):
        if "=" in line:
            key, val = line.split("=", 1)
            metrics[key] = val

    return metrics


def process_milc(spec, system, logs_dir):
    """Process all MILC logs using AWK tool + Python computation."""
    total_nodes = system["system"]["total_nodes"]
    output_dir = spec["tools"]["milc_validation"]["output_dir"]

    milc_logs = sorted([f for f in os.listdir(logs_dir) if f.startswith("milc_")])
    runs = []

    for log_file in milc_logs:
        path = os.path.join(logs_dir, log_file)
        metrics = run_milc_awk_validation(path, spec, output_dir)

        nodes = int(metrics["nodes"])
        step_time = float(metrics["traj2_mean_gftime"])
        olcf_fom = float(metrics["olcf_fom"])
        plaq = float(metrics["final_plaquette"])
        dev_pct = float(metrics["deviation_pct"])
        valid = metrics["validation"] == "PASS"

        replicas = math.floor(total_nodes / nodes)
        final_fom = replicas * olcf_fom

        runs.append({
            "log_file": log_file,
            "nodes": nodes,
            "traj2_mean_step_time": step_time,
            "olcf_fom": olcf_fom,
            "replicas": replicas,
            "final_fom": final_fom,
            "plaquette": plaq,
            "plaquette_deviation_pct": dev_pct,
            "validation_passed": valid,
        })

    return runs


# ---------------------------------------------------------------------------
# Workflow parser
# ---------------------------------------------------------------------------

def parse_workflow_log(path):
    with open(path) as f:
        text = f.read()

    dim_match = re.search(r"dimensions=(\d+)x(\d+)x(\d+)", text)
    dims = [int(dim_match.group(i)) for i in range(1, 4)]
    num_voxels = dims[0] * dims[1] * dims[2]

    rep_match = re.search(r"replicas=(\d+)", text)
    num_replicas = int(rep_match.group(1)) if rep_match else 1

    make_match = re.search(r"Total makespan:\s*([\d.]+)\s*seconds", text)
    makespan = float(make_match.group(1))

    losses = []
    for m in re.finditer(r"Epoch\s+\d+/\d+:\s*loss=([\d.]+)", text):
        losses.append(float(m.group(1)))

    return {
        "num_voxels": num_voxels,
        "num_replicas": num_replicas,
        "makespan": makespan,
        "final_loss": losses[-1] if losses else None,
    }


# ---------------------------------------------------------------------------
# SQLite database
# ---------------------------------------------------------------------------

def create_database(lammps_runs, milc_runs, wf_runs, scaling_data):
    """Create and populate SQLite database from parsed results."""
    db_path = "/app/results.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    with open("/app/db_schema.sql") as f:
        schema_sql = f.read()

    conn = sqlite3.connect(db_path)
    conn.executescript(schema_sql)

    for r in lammps_runs:
        conn.execute(
            "INSERT INTO lammps_runs VALUES (?, ?, ?, ?, ?, ?, ?)",
            (r["log_file"], r["num_atoms"], r["num_timesteps"],
             r["wall_time_seconds"], r["fom"], r["pe_per_molecule"],
             1 if r["validation_passed"] else 0),
        )

    for r in milc_runs:
        conn.execute(
            "INSERT INTO milc_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (r["log_file"], r["nodes"], r["traj2_mean_step_time"],
             r["olcf_fom"], r["replicas"], r["final_fom"],
             r["plaquette"], r["plaquette_deviation_pct"],
             1 if r["validation_passed"] else 0),
        )

    for r in wf_runs:
        conn.execute(
            "INSERT INTO workflow_runs VALUES (?, ?, ?, ?, ?, ?, ?)",
            (r["log_file"], r["num_voxels"], r["num_replicas"],
             r["makespan_seconds"], r["fom"], r["final_loss"],
             1 if r["validation_passed"] else 0),
        )

    for d in scaling_data:
        conn.execute(
            "INSERT INTO milc_scaling VALUES (?, ?, ?, ?)",
            (d["nodes"], d["step_time"], d["speedup"],
             d["parallel_efficiency"]),
        )

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    spec = load_toml("/app/spec.toml")
    system = load_toml("/app/system.toml")
    total_nodes = system["system"]["total_nodes"]
    logs_dir = "/app/logs"

    # --- LAMMPS ---
    lammps_logs = sorted([f for f in os.listdir(logs_dir) if f.startswith("lammps_")])
    lammps_runs = []
    for log_file in lammps_logs:
        path = os.path.join(logs_dir, log_file)
        parsed = parse_lammps_log(path)
        fom = compute_lammps_fom(parsed)
        valid, pe_per_mol = validate_lammps(parsed, spec)
        lammps_runs.append({
            "log_file": log_file,
            "num_atoms": parsed["num_atoms"],
            "num_timesteps": parsed["num_timesteps"],
            "wall_time_seconds": parsed["wall_time"],
            "fom": fom,
            "pe_per_molecule": pe_per_mol,
            "validation_passed": valid,
        })

    valid_lammps = [r for r in lammps_runs if r["validation_passed"]]
    if valid_lammps:
        valid_lammps.sort(key=lambda r: r["num_atoms"], reverse=True)
        best_lammps_fom = valid_lammps[0]["fom"]
    else:
        best_lammps_fom = 0.0

    # --- MILC (via AWK tool) ---
    milc_runs = process_milc(spec, system, logs_dir)

    valid_milc = [r for r in milc_runs if r["validation_passed"]]
    if valid_milc:
        optimal = max(valid_milc, key=lambda r: r["final_fom"])
        optimal_config = {
            "nodes_per_replica": optimal["nodes"],
            "replicas": optimal["replicas"],
            "olcf_fom": optimal["olcf_fom"],
            "final_fom": optimal["final_fom"],
        }
        best_milc_fom = optimal["final_fom"]
    else:
        optimal_config = {
            "nodes_per_replica": 0, "replicas": 0,
            "olcf_fom": 0.0, "final_fom": 0.0,
        }
        best_milc_fom = 0.0

    # --- Scaling Analysis ---
    valid_milc_sorted = sorted(valid_milc, key=lambda r: r["nodes"])
    ref_step_time = valid_milc_sorted[0]["traj2_mean_step_time"]
    ref_nodes = valid_milc_sorted[0]["nodes"]

    scaling_data = []
    for r in valid_milc_sorted:
        speedup = ref_step_time / r["traj2_mean_step_time"]
        efficiency = speedup / (r["nodes"] / ref_nodes)
        scaling_data.append({
            "nodes": r["nodes"],
            "step_time": r["traj2_mean_step_time"],
            "speedup": speedup,
            "parallel_efficiency": efficiency,
        })

    # --- Workflow ---
    wf_logs = sorted([f for f in os.listdir(logs_dir) if f.startswith("workflow_")])
    wf_runs = []
    best_wf_fom = 0.0
    for log_file in wf_logs:
        path = os.path.join(logs_dir, log_file)
        parsed = parse_workflow_log(path)
        fom = (parsed["num_voxels"] * parsed["num_replicas"]) / parsed["makespan"]
        threshold = spec["benchmarks"]["workflow"]["validation"]["threshold"]
        valid = parsed["final_loss"] is not None and parsed["final_loss"] < threshold
        wf_runs.append({
            "log_file": log_file,
            "num_voxels": parsed["num_voxels"],
            "num_replicas": parsed["num_replicas"],
            "makespan_seconds": parsed["makespan"],
            "fom": fom,
            "final_loss": parsed["final_loss"],
            "validation_passed": valid,
        })
        if valid and fom > best_wf_fom:
            best_wf_fom = fom

    # --- Create SQLite Database ---
    create_database(lammps_runs, milc_runs, wf_runs, scaling_data)

    # --- Aggregate Score ---
    aggregate_score = 0.0
    for bench_key in ["lammps", "milc", "workflow"]:
        weight = spec["benchmarks"][bench_key]["weight"]
        ref_fom = spec["benchmarks"][bench_key]["reference_fom"]
        if bench_key == "lammps":
            best = best_lammps_fom
        elif bench_key == "milc":
            best = best_milc_fom
        else:
            best = best_wf_fom
        aggregate_score += weight * (best / ref_fom)

    # --- Build Report ---
    report = {
        "system": {
            "name": system["system"]["name"],
            "total_nodes": total_nodes,
        },
        "benchmarks": {
            "lammps": {
                "runs": lammps_runs,
                "best_valid_fom": best_lammps_fom,
            },
            "milc": {
                "runs": milc_runs,
                "optimal_config": optimal_config,
                "best_valid_fom": best_milc_fom,
            },
            "workflow": {
                "runs": wf_runs,
                "best_valid_fom": best_wf_fom,
            },
        },
        "scaling_analysis": {
            "benchmark": "milc",
            "reference_nodes": ref_nodes,
            "data_points": scaling_data,
        },
        "aggregate_score": aggregate_score,
    }

    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report written to /app/report.json")
    print(f"Database written to /app/results.db")
    print(f"Aggregate score: {aggregate_score:.6f}")


if __name__ == "__main__":
    main()
