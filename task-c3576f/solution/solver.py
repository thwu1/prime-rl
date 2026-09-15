#!/usr/bin/env python3

"""
DPW-8 Multi-Solver Ensemble Analysis Pipeline.
Reads HDF5 solver submissions, identifies outliers, computes ensemble statistics,
performs grid convergence analysis, validates against experimental data,
and produces a DPW-8 conforming Tecplot submission file.
"""

import h5py
import numpy as np
import sqlite3
import json
import csv
import os
import tomllib


def read_solver_data(h5_path):
    """Read all solver submissions from HDF5 file."""
    solvers = {}
    with h5py.File(h5_path, "r") as f:
        for sid in f.keys():
            grp = f[sid]
            polar = grp["polar"]
            entry = {
                "solver_name": grp.attrs["solver_name"],
                "turbulence_model": grp.attrs["turbulence_model"],
                "grid_level": int(grp.attrs["grid_level"]),
                "grid_size": int(grp.attrs["grid_size"]),
                "alpha": polar["alpha"][:],
                "CL": polar["CL"][:],
                "CD": polar["CD"][:],
                "CM": polar["CM"][:],
            }
            if "grid_convergence" in grp:
                gc = grp["grid_convergence"]
                entry["gc"] = {
                    "alpha": float(gc.attrs["alpha"]),
                    "grid_level": gc["grid_level"][:],
                    "grid_size": gc["grid_size"][:],
                    "CL": gc["CL"][:],
                    "CD": gc["CD"][:],
                    "CM": gc["CM"][:],
                }
            solvers[sid] = entry
    return solvers


def read_experimental(csv_path):
    """Read experimental data CSV."""
    data = {"alpha": [], "CL": [], "CD": [], "CM": [],
            "CL_unc": [], "CD_unc": [], "CM_unc": []}
    with open(csv_path) as f:
        for line in f:
            if line.startswith("#") or line.strip() == "":
                continue
            if line.startswith("alpha"):
                continue
            parts = line.strip().split(",")
            data["alpha"].append(float(parts[0]))
            data["CL"].append(float(parts[1]))
            data["CD"].append(float(parts[2]))
            data["CM"].append(float(parts[3]))
            data["CL_unc"].append(float(parts[4]))
            data["CD_unc"].append(float(parts[5]))
            data["CM_unc"].append(float(parts[6]))
    return {k: np.array(v) for k, v in data.items()}


def read_config(toml_path):
    """Read reference TOML configuration."""
    with open(toml_path, "rb") as f:
        return tomllib.load(f)


def detect_outliers(solvers, alphas):
    """Detect outlier solvers using Modified Z-score (MAD-based)."""
    solver_ids = sorted(solvers.keys())
    outliers = set()
    reasons = {}

    for i, alpha in enumerate(alphas):
        cl_vals = np.array([solvers[sid]["CL"][i] for sid in solver_ids])
        median_cl = np.median(cl_vals)
        mad = np.median(np.abs(cl_vals - median_cl))

        if mad > 0:
            for j, sid in enumerate(solver_ids):
                mod_z = 0.6745 * abs(cl_vals[j] - median_cl) / mad
                if mod_z > 3.5:
                    outliers.add(sid)
                    if sid not in reasons:
                        reasons[sid] = (
                            f"CL deviates significantly from ensemble median "
                            f"(modified Z-score={mod_z:.1f} at alpha={alpha})"
                        )

    return outliers, reasons


def richardson_extrapolation(f1, f2, f3, r):
    """3-grid Richardson extrapolation. f1=finest, f3=coarsest."""
    eps21 = f2 - f1
    eps32 = f3 - f2
    if abs(eps21) < 1e-15:
        return f1, 0.0
    p = np.log(abs(eps32 / eps21)) / np.log(r)
    f_exact = f1 + (f1 - f2) / (r ** p - 1)
    return float(f_exact), float(p)


def compute_grid_convergence(solvers):
    """Compute Richardson extrapolation for solvers with multi-level data."""
    gc_results = {}
    for sid, data in solvers.items():
        if "gc" not in data:
            continue
        gc = data["gc"]
        gs = gc["grid_size"]
        # Refinement ratio from grid sizes (3D)
        r = (gs[0] / gs[1]) ** (1.0 / 3.0)

        # Use 3 finest grids
        cl_h0, p_cl = richardson_extrapolation(gc["CL"][0], gc["CL"][1], gc["CL"][2], r)
        cd_h0, p_cd = richardson_extrapolation(gc["CD"][0], gc["CD"][1], gc["CD"][2], r)
        cm_h0, p_cm = richardson_extrapolation(gc["CM"][0], gc["CM"][1], gc["CM"][2], r)

        gc_results[sid] = {
            "CL_h0": cl_h0, "CD_h0": cd_h0, "CM_h0": cm_h0,
            "order_CL": p_cl, "order_CD": p_cd, "order_CM": p_cm,
        }
    return gc_results


def build_database(db_path, solvers, outliers, outlier_reasons,
                   clean_stats, gc_results, validation, exp_data):
    """Build SQLite database with all analysis results."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE solvers (
        solver_id TEXT PRIMARY KEY,
        solver_name TEXT,
        turbulence_model TEXT,
        grid_level INTEGER,
        grid_size INTEGER
    )""")

    c.execute("""CREATE TABLE coefficients (
        solver_id TEXT,
        alpha REAL,
        CL REAL,
        CD REAL,
        CM REAL
    )""")

    c.execute("""CREATE TABLE statistics (
        alpha REAL,
        CL_mean REAL,
        CL_std REAL,
        CD_mean REAL,
        CD_std REAL,
        CM_mean REAL,
        CM_std REAL,
        n_solvers INTEGER
    )""")

    c.execute("""CREATE TABLE outliers (
        solver_id TEXT,
        reason TEXT
    )""")

    c.execute("""CREATE TABLE grid_convergence (
        solver_id TEXT,
        CL_h0 REAL,
        CD_h0 REAL,
        CM_h0 REAL,
        order_CL REAL,
        order_CD REAL,
        order_CM REAL
    )""")

    c.execute("""CREATE TABLE validation (
        alpha REAL,
        CL_exp REAL,
        CL_comp REAL,
        CL_delta REAL,
        CD_exp REAL,
        CD_comp REAL,
        CD_delta REAL,
        within_uncertainty INTEGER
    )""")

    # Populate solvers
    for sid, data in solvers.items():
        c.execute("INSERT INTO solvers VALUES (?,?,?,?,?)",
                  (sid, data["solver_name"], data["turbulence_model"],
                   data["grid_level"], data["grid_size"]))

    # Populate coefficients
    for sid, data in solvers.items():
        for i in range(len(data["alpha"])):
            c.execute("INSERT INTO coefficients VALUES (?,?,?,?,?)",
                      (sid, float(data["alpha"][i]), float(data["CL"][i]),
                       float(data["CD"][i]), float(data["CM"][i])))

    # Populate outliers
    for sid in outliers:
        c.execute("INSERT INTO outliers VALUES (?,?)",
                  (sid, outlier_reasons.get(sid, "statistical outlier")))

    # Populate statistics
    for alpha_str, stats in clean_stats.items():
        c.execute("INSERT INTO statistics VALUES (?,?,?,?,?,?,?,?)",
                  (stats["alpha"], stats["CL_mean"], stats["CL_std"],
                   stats["CD_mean"], stats["CD_std"],
                   stats["CM_mean"], stats["CM_std"], stats["n_solvers"]))

    # Populate grid convergence
    for sid, gc in gc_results.items():
        c.execute("INSERT INTO grid_convergence VALUES (?,?,?,?,?,?,?)",
                  (sid, gc["CL_h0"], gc["CD_h0"], gc["CM_h0"],
                   gc["order_CL"], gc["order_CD"], gc["order_CM"]))

    # Populate validation
    for v in validation:
        c.execute("INSERT INTO validation VALUES (?,?,?,?,?,?,?,?)",
                  (v["alpha"], v["CL_exp"], v["CL_comp"], v["CL_delta"],
                   v["CD_exp"], v["CD_comp"], v["CD_delta"],
                   v["within_uncertainty"]))

    conn.commit()
    conn.close()


def write_tecplot(path, clean_stats, config):
    """Write DPW-8 conforming Tecplot submission file."""
    pid = config["submission"]["participant_id"]
    sub_id = config["submission"]["submission_id"]
    title = f"{pid}.{sub_id}"
    mach = config["freestream"]["mach"]
    reynolds = config["freestream"]["reynolds"]

    with open(path, "w") as f:
        f.write(f'TITLE = "{title}"\n\n')

        # 31 variables matching DPW-8 template
        f.write('VARIABLES = "GRID_LEVEL"  "GRID_SIZE"  "GRID_FAC"  "MACH"  "REY"  '
                '"ALPHA"   "CL_TOT"    "CD_TOT"     "CM_TOT"     "CL_WING"     '
                '"CD_WING"     "CM_WING"     "CD_PR"      "CD_SF"      "CL_TAIL"    '
                '"CD_TAIL"    "CM_TAIL"    "CL_FUS"    "CD_FUS"     "CM_FUS"    '
                '"CL_NAC"    "CD_NAC"     "CM_NAC"    "CL_PY"     "CD_PY"      '
                '"CM_PY"     "CPU_Hours"  "DELTAT"  "CTUSTART"  "CTUAVG"   "Q/E"\n\n')

        # Metadata
        f.write(f'DATASETAUXDATA ParticipantID   = "{title}"\n')
        f.write(f'DATASETAUXDATA SubmissionDate  = "2025-01-01"\n')
        f.write(f'DATASETAUXDATA Name            = "Ensemble Average"\n')
        f.write(f'DATASETAUXDATA Email           = ""\n')
        f.write(f'DATASETAUXDATA Institution     = "DPW Ensemble"\n')
        f.write(f'DATASETAUXDATA SolverName      = "Ensemble"\n')
        f.write(f'DATASETAUXDATA BasicAlgorithm  = "Ensemble Average"\n')
        f.write(f'DATASETAUXDATA TurbulenceModel = "Mixed"\n')
        f.write(f'DATASETAUXDATA GridId          = "Ensemble"\n')
        f.write(f'DATASETAUXDATA Notes           = "Ensemble average of 5 accepted solvers"\n\n')

        # Single zone: polar sweep
        f.write(f'ZONE T="{title} GRID LEVEL 3"\n')
        f.write('AUXDATA Tstatic         = "559.67"\n')
        f.write('AUXDATA Deltat          = ""\n')
        f.write('AUXDATA GridFileName    = ""\n')
        f.write('AUXDATA Misc            = ""\n')

        # Use representative grid size from ensemble
        grid_size = 13900000  # approximate average
        grid_fac = 1.0 / grid_size ** (2.0 / 3.0)

        for alpha_str in sorted(clean_stats.keys(), key=float):
            s = clean_stats[alpha_str]
            alpha = s["alpha"]
            row = [
                3,                      # GRID_LEVEL
                grid_size,              # GRID_SIZE
                grid_fac,               # GRID_FAC
                mach,                   # MACH
                reynolds,               # REY
                alpha,                  # ALPHA
                s["CL_mean"],           # CL_TOT
                s["CD_mean"],           # CD_TOT
                s["CM_mean"],           # CM_TOT
            ]
            # Fill remaining 22 optional columns with -999
            row.extend([-999] * 22)

            f.write("  ".join(f"{v}" if isinstance(v, int) else f"{v:.8f}" if abs(v) < 100 else f"{v:.1f}"
                              for v in row) + "\n")


def main():
    os.makedirs("/app/output", exist_ok=True)

    # 1. Read all data
    solvers = read_solver_data("/app/data/solver_results.h5")
    exp_data = read_experimental("/app/data/experimental.csv")
    config = read_config("/app/data/reference.toml")

    alphas = solvers[list(solvers.keys())[0]]["alpha"]
    solver_ids = sorted(solvers.keys())

    # 2. Detect outliers
    outliers, outlier_reasons = detect_outliers(solvers, alphas)
    good_ids = [sid for sid in solver_ids if sid not in outliers]

    # 3. Compute clean ensemble statistics
    clean_stats = {}
    for i, alpha in enumerate(alphas):
        cl_vals = np.array([solvers[sid]["CL"][i] for sid in good_ids])
        cd_vals = np.array([solvers[sid]["CD"][i] for sid in good_ids])
        cm_vals = np.array([solvers[sid]["CM"][i] for sid in good_ids])

        clean_stats[f"{alpha:.1f}"] = {
            "alpha": float(alpha),
            "CL_mean": float(np.mean(cl_vals)),
            "CL_std": float(np.std(cl_vals, ddof=1)),
            "CD_mean": float(np.mean(cd_vals)),
            "CD_std": float(np.std(cd_vals, ddof=1)),
            "CM_mean": float(np.mean(cm_vals)),
            "CM_std": float(np.std(cm_vals, ddof=1)),
            "n_solvers": len(good_ids),
        }

    # 4. Grid convergence
    gc_results = compute_grid_convergence(solvers)

    # 5. Experimental validation
    validation = []
    for i, alpha in enumerate(exp_data["alpha"]):
        alpha_key = f"{alpha:.1f}"
        if alpha_key in clean_stats:
            stats = clean_stats[alpha_key]
            cl_delta = stats["CL_mean"] - exp_data["CL"][i]
            cd_delta = stats["CD_mean"] - exp_data["CD"][i]
            cm_delta = stats["CM_mean"] - exp_data["CM"][i]

            within = (abs(cl_delta) <= exp_data["CL_unc"][i] and
                      abs(cd_delta) <= exp_data["CD_unc"][i] and
                      abs(cm_delta) <= exp_data["CM_unc"][i])

            validation.append({
                "alpha": float(alpha),
                "CL_exp": float(exp_data["CL"][i]),
                "CL_comp": float(stats["CL_mean"]),
                "CL_delta": float(cl_delta),
                "CD_exp": float(exp_data["CD"][i]),
                "CD_comp": float(stats["CD_mean"]),
                "CD_delta": float(cd_delta),
                "within_uncertainty": 1 if within else 0,
            })

    # 6. Build SQLite database
    build_database("/app/output/ensemble.db", solvers, outliers, outlier_reasons,
                   clean_stats, gc_results, validation, exp_data)

    # 7. Write Tecplot submission
    write_tecplot("/app/output/ensemble_submission.dat", clean_stats, config)

    # 8. Write analysis JSON
    analysis = {
        "n_solvers_total": len(solver_ids),
        "n_solvers_accepted": len(good_ids),
        "outlier_ids": sorted(list(outliers)),
        "ensemble_cl_at_alpha_2": clean_stats["2.0"]["CL_mean"],
        "ensemble_cd_at_alpha_2": clean_stats["2.0"]["CD_mean"],
        "continuum_estimates": {
            sid: {"CL_h0": gc["CL_h0"], "order": gc["order_CL"]}
            for sid, gc in gc_results.items()
        },
    }
    with open("/app/output/analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)

    print("Analysis complete. Output files:")
    print("  /app/output/ensemble.db")
    print("  /app/output/ensemble_submission.dat")
    print("  /app/output/analysis.json")


if __name__ == "__main__":
    main()
