#!/usr/bin/env python3

"""
DPW-8 Grid Convergence V&V Assessment Pipeline

Parses DPW-8 Tecplot ASCII submission files, performs Richardson extrapolation,
computes GCI uncertainty, detects anomalous submissions, produces ensemble
statistics, creates SQLite database, and generates gnuplot convergence plot scripts.
"""

import json
import math
import os
import re
import sqlite3
import sys
from pathlib import Path


# ──────────────────────────────────────────────────────────────────
# Tecplot DPW-8 format parser
# ──────────────────────────────────────────────────────────────────

def parse_dpw_submission(filepath):
    """Parse a DPW-8 Tecplot ASCII force & moment submission file."""
    with open(filepath, "r") as f:
        lines = f.readlines()

    metadata = {}
    variables = []
    zones = []
    current_zone = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("TITLE"):
            m = re.match(r'TITLE\s*=\s*"([^"]*)"', line)
            if m:
                metadata["title"] = m.group(1)
            continue

        if line.startswith("VARIABLES"):
            variables = re.findall(r'"([^"]*)"', line)
            continue

        if line.startswith("DATASETAUXDATA"):
            m = re.match(r'DATASETAUXDATA\s+(\S+)\s*=\s*"([^"]*)"', line)
            if m:
                metadata[m.group(1)] = m.group(2)
            continue

        if line.startswith("ZONE"):
            m = re.match(r'ZONE\s+T\s*=\s*"([^"]*)"', line)
            if m:
                current_zone = {
                    "title": m.group(1),
                    "auxdata": {},
                    "data": []
                }
                zones.append(current_zone)
            continue

        if line.startswith("AUXDATA") and current_zone is not None:
            m = re.match(r'AUXDATA\s+(\S+)\s*=\s*"([^"]*)"', line)
            if m:
                current_zone["auxdata"][m.group(1)] = m.group(2)
            continue

        if current_zone is not None and (line[0].isdigit() or line[0] == '-'):
            parts = line.split()
            if len(parts) >= 9:
                try:
                    row = {}
                    for i, val_str in enumerate(parts):
                        if i < len(variables):
                            row[variables[i]] = float(val_str)
                    current_zone["data"].append(row)
                except ValueError:
                    pass

    return {"metadata": metadata, "variables": variables, "zones": zones}


def extract_grid_convergence(parsed, config="CRMWB"):
    """Extract grid convergence data for a specific configuration and alpha=2.50."""
    for zone in parsed["zones"]:
        title = zone["title"]
        auxdata = zone["auxdata"]

        zone_config = auxdata.get("Configuration", "")
        if zone_config != config:
            if config not in title:
                continue

        if "ALPHA" in title and "GRID LEVEL" not in title:
            alpha_match = re.search(r'ALPHA\s+([\d.]+)', title)
            if alpha_match:
                alpha = float(alpha_match.group(1))
                if abs(alpha - 2.50) > 0.01:
                    continue

            gc_data = {}
            for row in zone["data"]:
                level = int(row.get("GRID_LEVEL", -1))
                if level < 1:
                    continue
                gc_data[level] = {
                    "CL": row.get("CL_TOT", None),
                    "CD": row.get("CD_TOT", None),
                    "CM": row.get("CM_TOT", None),
                    "GRID_SIZE": int(row.get("GRID_SIZE", 0)),
                }
            if gc_data:
                return gc_data

    return None


def parse_experimental_reference(filepath):
    """Parse the experimental reference data file."""
    with open(filepath, "r") as f:
        lines = f.readlines()

    exp_data = {}
    variables = []
    in_zone = False

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("VARIABLES"):
            variables = re.findall(r'"([^"]*)"', line)
            continue
        if line.startswith("ZONE"):
            in_zone = True
            continue
        if line.startswith("AUXDATA"):
            continue
        if in_zone and (line[0].isdigit() or line[0] == '-'):
            parts = line.split()
            if len(parts) >= 4:
                alpha = float(parts[0])
                cl = float(parts[1])
                cd = float(parts[2])
                cm = float(parts[3])
                exp_data[alpha] = {"CL": cl, "CD": cd, "CM": cm}

    return exp_data


# ──────────────────────────────────────────────────────────────────
# Richardson Extrapolation
# ──────────────────────────────────────────────────────────────────

def richardson_extrapolation(f2, f3, f4, r):
    """Three-grid Richardson extrapolation with GCI uncertainty.

    Args:
        f2: solution on medium grid
        f3: solution on fine grid
        f4: solution on finest grid
        r: refinement ratio

    Returns:
        dict with convergence_order, asymptotic_value, numerical_uncertainty, monotonic
    """
    e32 = f2 - f3
    e43 = f3 - f4

    result = {
        "monotonic": True,
        "convergence_order": None,
        "asymptotic_value": None,
        "numerical_uncertainty": None,
    }

    if abs(e43) < 1e-15 or abs(e32) < 1e-15:
        result["monotonic"] = False
        return result

    if e32 * e43 <= 0:
        result["monotonic"] = False
        return result

    ratio = abs(e32 / e43)

    if abs(ratio - 1.0) < 1e-12:
        result["convergence_order"] = 0.0
        return result

    p = math.log(ratio) / math.log(r)
    result["convergence_order"] = p

    if p < 0:
        result["monotonic"] = False
        return result

    rp = r ** p
    f_re = f4 + (f4 - f3) / (rp - 1)
    result["asymptotic_value"] = f_re

    # GCI with safety factor 1.25 for three-grid studies
    gci = 1.25 * abs(e43 / f4) / (rp - 1)
    result["numerical_uncertainty"] = gci

    return result


# ──────────────────────────────────────────────────────────────────
# SQLite database creation
# ──────────────────────────────────────────────────────────────────

def create_sqlite_db(db_path, gc_data_all, participants_results, flagged):
    """Create SQLite database with raw data and convergence assessment."""
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    c.execute("""CREATE TABLE raw_data (
        participant_id TEXT,
        grid_level INTEGER,
        grid_size INTEGER,
        cl REAL,
        cd REAL,
        cm REAL,
        solver TEXT,
        turbulence_model TEXT
    )""")

    c.execute("""CREATE TABLE convergence_assessment (
        participant_id TEXT,
        coefficient TEXT,
        convergence_order REAL,
        asymptotic_value REAL,
        numerical_uncertainty REAL,
        is_valid INTEGER
    )""")

    # Insert raw data
    for pid in sorted(gc_data_all.keys()):
        gc = gc_data_all[pid]
        solver = participants_results[pid]["solver"]
        turb = participants_results[pid]["turbulence_model"]
        for level in sorted(gc.keys()):
            row = gc[level]
            c.execute(
                "INSERT INTO raw_data VALUES (?,?,?,?,?,?,?,?)",
                (pid, level, row["GRID_SIZE"], row["CL"], row["CD"],
                 row["CM"], solver, turb)
            )

    # Insert convergence assessment
    for pid in sorted(participants_results.keys()):
        is_anomalous = pid in flagged
        for coeff in ["CL", "CD", "CM"]:
            entry = participants_results[pid][coeff]
            has_valid_result = (
                entry["convergence_order"] is not None
                and entry["asymptotic_value"] is not None
                and entry["convergence_order"] >= 0.5
            )
            c.execute(
                "INSERT INTO convergence_assessment VALUES (?,?,?,?,?,?)",
                (pid, coeff,
                 entry["convergence_order"],
                 entry["asymptotic_value"],
                 entry["numerical_uncertainty"],
                 1 if has_valid_result else 0)
            )

    conn.commit()
    conn.close()


# ──────────────────────────────────────────────────────────────────
# Gnuplot file generation
# ──────────────────────────────────────────────────────────────────

def generate_gnuplot_files(plots_dir, gc_data_all, participants_results):
    """Generate gnuplot data files and scripts for convergence plots."""
    plots_dir.mkdir(parents=True, exist_ok=True)

    pids = sorted(gc_data_all.keys())

    # Write per-participant data files
    for pid in pids:
        gc = gc_data_all[pid]
        safe_pid = pid.replace(".", "_")
        with open(plots_dir / f"data_{safe_pid}.dat", "w") as f:
            f.write(f"# Participant {pid}\n")
            f.write("# grid_fac  CL  CD  CM\n")
            for level in sorted(gc.keys()):
                row = gc[level]
                gf = 1.0 / (row["GRID_SIZE"] ** (2.0 / 3.0))
                f.write(f"{gf:.10e}  {row['CL']:.8f}  "
                        f"{row['CD']:.10f}  {row['CM']:.8f}\n")

    # Write asymptotic estimates data file
    with open(plots_dir / "asymptotic.dat", "w") as f:
        f.write("# Asymptotic estimates (grid_fac=0)\n")
        f.write("# grid_fac  CL  CD  CM\n")
        for pid in pids:
            pdata = participants_results[pid]
            cl_a = pdata["CL"].get("asymptotic_value")
            cd_a = pdata["CD"].get("asymptotic_value")
            cm_a = pdata["CM"].get("asymptotic_value")
            if cl_a is not None and cd_a is not None and cm_a is not None:
                f.write(f"0.0  {cl_a:.8f}  {cd_a:.10f}  {cm_a:.8f}\n")

    # Generate gnuplot scripts for each coefficient
    coeff_info = [("cl", "C_L", 2), ("cd", "C_D", 3), ("cm", "C_M", 4)]
    for coeff_lower, coeff_label, col in coeff_info:
        lines = [
            f"set terminal pngcairo size 900,600 font ',11'",
            f"set output '{coeff_lower}_convergence.png'",
            f"set xlabel 'Grid Factor (1/N^{{2/3}})'",
            f"set ylabel '{coeff_label}'",
            f"set title '{coeff_label} Grid Convergence - DPW-8 CRMWB'",
            f"set key outside right",
            f"set grid",
            f"",
        ]

        plot_parts = []
        for pid in pids:
            safe_pid = pid.replace(".", "_")
            plot_parts.append(
                f"'data_{safe_pid}.dat' using 1:{col} "
                f"with linespoints lw 2 pt 7 title '{pid}'"
            )
        plot_parts.append(
            f"'asymptotic.dat' using 1:{col} "
            f"with points pt 5 ps 2 lc rgb 'black' title 'Asymptotic'"
        )

        lines.append("plot " + ", \\\n     ".join(plot_parts))

        with open(plots_dir / f"plot_{coeff_lower}.gp", "w") as f:
            f.write("\n".join(lines) + "\n")


# ──────────────────────────────────────────────────────────────────
# Main analysis
# ──────────────────────────────────────────────────────────────────

def main():
    submissions_dir = Path("/app/submissions")
    experimental_path = Path("/app/experimental/crm_wb_etw.dat")
    results_dir = Path("/app/results")
    plots_dir = results_dir / "plots"
    results_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    # Parse experimental data
    exp_data = parse_experimental_reference(str(experimental_path))
    exp_at_250 = exp_data.get(2.50, {})

    # Parse all submissions
    submission_files = sorted(submissions_dir.glob("participant_*.dat"))
    participants_results = {}
    gc_data_all = {}
    all_grid_sizes = None

    for fpath in submission_files:
        parsed = parse_dpw_submission(str(fpath))
        pid = parsed["metadata"].get("ParticipantID",
                                     parsed["metadata"].get("title", ""))
        solver = parsed["metadata"].get("SolverName", "unknown")
        turb = parsed["metadata"].get("TurbulenceModel", "unknown")

        gc_data = extract_grid_convergence(parsed, config="CRMWB")
        if gc_data is None:
            print(f"WARNING: No CRMWB grid convergence data found for {pid}")
            continue

        gc_data_all[pid] = gc_data
        levels = sorted(gc_data.keys())
        if len(levels) < 3:
            print(f"WARNING: Fewer than 3 grid levels for {pid}")
            continue

        grid_sizes = [gc_data[lv]["GRID_SIZE"] for lv in levels]
        if all_grid_sizes is None:
            all_grid_sizes = grid_sizes

        # Compute refinement ratio from grid sizes (3D: h ~ N^(-1/3))
        finest_3_levels = levels[-3:]
        n2 = gc_data[finest_3_levels[0]]["GRID_SIZE"]
        n3 = gc_data[finest_3_levels[1]]["GRID_SIZE"]
        n4 = gc_data[finest_3_levels[2]]["GRID_SIZE"]

        r_32 = (n3 / n2) ** (1.0 / 3.0)
        r_43 = (n4 / n3) ** (1.0 / 3.0)
        r = (r_32 + r_43) / 2.0

        p_result = {
            "solver": solver,
            "turbulence_model": turb,
        }

        for coeff in ["CL", "CD", "CM"]:
            f2 = gc_data[finest_3_levels[0]][coeff]
            f3 = gc_data[finest_3_levels[1]][coeff]
            f4 = gc_data[finest_3_levels[2]][coeff]

            re_result = richardson_extrapolation(f2, f3, f4, r)

            p_result[coeff] = {
                "convergence_order": re_result["convergence_order"],
                "asymptotic_value": re_result["asymptotic_value"],
                "numerical_uncertainty": re_result["numerical_uncertainty"],
            }

        participants_results[pid] = p_result

    # Write grid_convergence.json
    gc_output = {
        "participants": participants_results,
        "refinement_ratio": r,
        "grid_sizes": all_grid_sizes if all_grid_sizes else [],
    }
    with open(results_dir / "grid_convergence.json", "w") as f:
        json.dump(gc_output, f, indent=2)
    print("Written: grid_convergence.json")

    # Anomaly detection
    flagged = {}
    for pid, pdata in participants_results.items():
        reasons = []
        affected_coeffs = []

        for coeff in ["CL", "CD", "CM"]:
            entry = pdata[coeff]

            if entry["asymptotic_value"] is None:
                reasons.append(
                    f"Non-monotonic or degenerate grid convergence in {coeff}"
                )
                affected_coeffs.append(coeff)
                continue

            order = entry.get("convergence_order")
            if order is not None and order < 0.5:
                reasons.append(
                    f"Pathologically low convergence order in {coeff}: "
                    f"p = {order:.3f}"
                )
                affected_coeffs.append(coeff)

        if reasons:
            flagged[pid] = {
                "reasons": reasons,
                "coefficients_affected": list(set(affected_coeffs)),
            }

    anomalies_output = {"flagged": flagged}
    with open(results_dir / "anomalies.json", "w") as f:
        json.dump(anomalies_output, f, indent=2)
    print("Written: anomalies.json")

    # Ensemble statistics (valid participants only)
    valid_pids = sorted(
        pid for pid in participants_results if pid not in flagged
    )

    stats = {}
    for coeff in ["CL", "CD", "CM"]:
        re_vals = []
        for pid in valid_pids:
            val = participants_results[pid][coeff]["asymptotic_value"]
            if val is not None:
                re_vals.append(val)

        if re_vals:
            n = len(re_vals)
            mean_val = sum(re_vals) / n
            if n > 1:
                std_val = math.sqrt(
                    sum((v - mean_val) ** 2 for v in re_vals) / (n - 1)
                )
            else:
                std_val = 0.0

            stats[coeff] = {
                "mean": mean_val,
                "std": std_val,
            }

    ensemble_output = {
        "valid_participants": valid_pids,
        "statistics": stats,
        "experimental_reference": {
            "CL": exp_at_250.get("CL"),
            "CD": exp_at_250.get("CD"),
            "CM": exp_at_250.get("CM"),
        },
    }
    with open(results_dir / "ensemble.json", "w") as f:
        json.dump(ensemble_output, f, indent=2)
    print("Written: ensemble.json")

    # Create SQLite database
    db_path = results_dir / "convergence.db"
    create_sqlite_db(db_path, gc_data_all, participants_results, flagged)
    print(f"Written: {db_path}")

    # Generate gnuplot data files and scripts
    generate_gnuplot_files(plots_dir, gc_data_all, participants_results)
    print(f"Written gnuplot files to {plots_dir}")

    # Summary
    print(f"\nAnalysis complete:")
    print(f"  Total participants: {len(participants_results)}")
    print(f"  Flagged anomalous: {len(flagged)} ({', '.join(flagged.keys())})")
    print(f"  Valid for ensemble: {len(valid_pids)} ({', '.join(valid_pids)})")


if __name__ == "__main__":
    main()
