"""
CFD Solver Benchmark Evaluation Pipeline.

Parses five solver submissions in different formats, performs grid convergence
analysis via Richardson extrapolation, computes accuracy metrics against
experimental data, detects anomalies, ranks solvers, and generates gnuplot
comparison plots.

"""

import csv
import json
import math
import os
import re
import subprocess


# ================================================================== #
#  Data Structures                                                     #
# ================================================================== #

class SolverData:
    """Holds parsed data for one solver submission."""
    def __init__(self, name):
        self.name = name
        # Grid convergence data: list of (level, n_cells, alpha, CL, CD, CM)
        self.convergence = []
        # Alpha sweep data: list of (level, n_cells, alpha, CL, CD, CM)
        self.sweep = []


# ================================================================== #
#  Parsers                                                             #
# ================================================================== #

def parse_experiment(filepath):
    """Parse experimental reference CSV."""
    alphas, cls, cds, cms = [], [], [], []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('alpha'):
                continue
            parts = line.split(',')
            alphas.append(float(parts[0]))
            cls.append(float(parts[1]))
            cds.append(float(parts[2]))
            cms.append(float(parts[3]))
    return alphas, cls, cds, cms


def parse_grid_spec(filepath):
    """Parse grid specification CSV."""
    levels = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('level'):
                continue
            parts = line.split(',')
            levels[int(parts[0])] = int(parts[1])
    return levels


def parse_tecplot(filepath, solver_name):
    """Parse Tecplot ASCII format (FUN3D submission)."""
    data = SolverData(solver_name)
    with open(filepath) as f:
        content = f.read()

    lines = content.strip().split('\n')
    current_section = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('TITLE') or stripped.startswith('VARIABLES'):
            continue
        if 'ZONE' in stripped:
            if 'Convergence' in stripped or 'convergence' in stripped:
                current_section = 'convergence'
            elif 'Sweep' in stripped or 'sweep' in stripped:
                current_section = 'sweep'
            continue
        if current_section is None:
            continue

        parts = stripped.split()
        try:
            vals = [float(p) for p in parts]
            if len(vals) >= 6:
                row = (int(vals[0]), int(vals[1]), vals[2], vals[3], vals[4], vals[5])
                if current_section == 'convergence':
                    data.convergence.append(row)
                else:
                    data.sweep.append(row)
        except ValueError:
            continue

    return data


def parse_csv_submission(filepath, solver_name):
    """Parse CSV with comment-header format (OVERFLOW submission)."""
    data = SolverData(solver_name)
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('section'):
                continue  # header line
            parts = line.split(',')
            if len(parts) < 7:
                continue
            section = parts[0].strip()
            row = (int(parts[1]), int(parts[2]), float(parts[3]),
                   float(parts[4]), float(parts[5]), float(parts[6]))
            if section == 'convergence':
                data.convergence.append(row)
            elif section == 'sweep':
                data.sweep.append(row)

    return data


def parse_fixed_width(filepath, solver_name):
    """Parse Fortran fixed-width format (SU2 submission)."""
    data = SolverData(solver_name)
    current_section = None

    with open(filepath) as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith('*'):
                continue
            if 'GRID CONVERGENCE' in stripped.upper():
                current_section = 'convergence'
                continue
            if 'ALPHA SWEEP' in stripped.upper():
                current_section = 'sweep'
                continue
            if stripped.startswith('---') or stripped.startswith('LVL'):
                continue
            if current_section is None:
                continue

            # Parse fixed-width / space-separated fields
            parts = stripped.split()
            if len(parts) < 6:
                continue
            try:
                level = int(parts[0])
                ncells = int(parts[1])
                alpha = float(parts[2])
                cl = float(parts[3])
                cd = float(parts[4])
                cm = float(parts[5])
                row = (level, ncells, alpha, cl, cd, cm)
                if current_section == 'convergence':
                    data.convergence.append(row)
                else:
                    data.sweep.append(row)
            except (ValueError, IndexError):
                continue

    return data


def parse_jsonl(filepath, solver_name):
    """Parse JSON-lines format (TAU submission)."""
    data = SolverData(solver_name)
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            row = (obj["grid_level"], obj["n_cells"], obj["alpha"],
                   obj["CL"], obj["CD"], obj["CM"])
            if obj["section"] == "convergence":
                data.convergence.append(row)
            elif obj["section"] == "sweep":
                data.sweep.append(row)

    return data


def parse_tsv(filepath, solver_name):
    """Parse TSV with metadata comment blocks (CFL3D submission)."""
    data = SolverData(solver_name)
    current_section = None

    with open(filepath) as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith('##'):
                if 'Grid Convergence' in stripped or 'convergence' in stripped:
                    current_section = 'convergence'
                elif 'Alpha Sweep' in stripped or 'sweep' in stripped:
                    current_section = 'sweep'
                continue
            if stripped.startswith('Level') or stripped.startswith('level'):
                continue  # header
            if current_section is None:
                continue

            parts = stripped.split('\t')
            if len(parts) < 6:
                continue
            try:
                row = (int(parts[0]), int(parts[1]), float(parts[2]),
                       float(parts[3]), float(parts[4]), float(parts[5]))
                if current_section == 'convergence':
                    data.convergence.append(row)
                else:
                    data.sweep.append(row)
            except (ValueError, IndexError):
                continue

    return data


# ================================================================== #
#  Richardson Extrapolation                                            #
# ================================================================== #

def richardson_extrapolation(f_values, r=2.0):
    """
    Perform Richardson extrapolation using three successive grid levels.

    f_values: list of (h_characteristic, f_value) sorted from coarse to fine
    r: grid refinement ratio

    Returns: (observed_order_p, extrapolated_value)
    """
    if len(f_values) < 3:
        raise ValueError("Need at least 3 grid levels for Richardson extrapolation")

    # Use the three finest grids
    f3 = f_values[-3][1]  # coarsest of the three
    f2 = f_values[-2][1]  # middle
    f1 = f_values[-1][1]  # finest

    diff_32 = f3 - f2
    diff_21 = f2 - f1

    if abs(diff_21) < 1e-15:
        # Already converged
        return 2.0, f1

    ratio = diff_32 / diff_21
    if ratio <= 0:
        # Non-monotone convergence
        return float('nan'), f1

    p = math.log(ratio) / math.log(r)
    f_extrap = f1 + (f1 - f2) / (r**p - 1)

    return p, f_extrap


def detect_anomaly(convergence_data, r=2.0):
    """
    Detect anomalous convergence behavior by checking if any data point
    is inconsistent with the convergence trend of the remaining points.

    Returns: (has_anomaly: bool, clean_data: list)
    """
    if len(convergence_data) <= 3:
        return False, convergence_data

    # Sort by grid level (coarsest first)
    sorted_data = sorted(convergence_data, key=lambda x: x[0])

    # Check if removing the coarsest grid gives a much better Richardson fit
    # Try Richardson with all levels (using 3 finest)
    cl_all = [(1.0 / math.sqrt(row[1]), row[3]) for row in sorted_data]
    p_all, _ = richardson_extrapolation(cl_all, r)

    # Try Richardson without the coarsest level
    cl_fine = [(1.0 / math.sqrt(row[1]), row[3]) for row in sorted_data[1:]]
    p_fine, _ = richardson_extrapolation(cl_fine, r)

    # If the coarsest grid causes unreasonable convergence order,
    # flag as anomaly
    if math.isnan(p_all) or abs(p_all) > 5.0:
        # The coarsest grid is disrupting the convergence
        return True, sorted_data[1:]

    # Check if coarsest value deviates significantly from the trend
    # predicted by the finer grids
    if len(sorted_data) >= 4:
        h_coarsest = 1.0 / math.sqrt(sorted_data[0][1])
        h_next = 1.0 / math.sqrt(sorted_data[1][1])
        cl_coarsest = sorted_data[0][3]
        cl_next = sorted_data[1][3]

        # Predict coarsest value from the fine-grid trend
        if not math.isnan(p_fine):
            _, extrap = richardson_extrapolation(cl_fine, r)
            # Predicted value at coarsest grid using the fine-grid order
            predicted = extrap + (cl_fine[0][1] - extrap) * (h_coarsest / h_next) ** p_fine
            deviation = abs(cl_coarsest - predicted)
            # If deviation is much larger than the fine-grid range, flag anomaly
            fine_range = abs(cl_fine[0][1] - cl_fine[-1][1])
            if fine_range > 0 and deviation > 3.0 * fine_range:
                return True, sorted_data[1:]

    return False, sorted_data


# ================================================================== #
#  Accuracy Metrics                                                    #
# ================================================================== #

def rms_error(predicted, reference):
    """Compute RMS error between two lists."""
    if len(predicted) != len(reference):
        raise ValueError("Lists must have same length")
    n = len(predicted)
    if n == 0:
        return 0.0
    ss = sum((p - r) ** 2 for p, r in zip(predicted, reference))
    return math.sqrt(ss / n)


# ================================================================== #
#  Gnuplot Generation                                                  #
# ================================================================== #

def generate_convergence_plot(all_solvers, grid_spec):
    """Generate gnuplot script and data for grid convergence plot."""
    # Write convergence data file
    with open("/app/plots/conv_data.dat", "w") as f:
        f.write("# h  ")
        for s in all_solvers:
            f.write(f"CL_{s.name}  ")
        f.write("\n")

        # Collect all grid levels
        levels = sorted(grid_spec.keys())
        for lvl in levels:
            h = 1.0 / math.sqrt(grid_spec[lvl])
            f.write(f"{h:.8f}")
            for s in all_solvers:
                cl_val = None
                for row in s.convergence:
                    if row[0] == lvl:
                        cl_val = row[3]
                        break
                if cl_val is not None:
                    f.write(f"  {cl_val:.6f}")
                else:
                    f.write("  NaN")
            f.write("\n")

    # Write gnuplot script
    script = """set terminal pngcairo size 900,600 enhanced font 'Arial,12'
set output '/app/plots/convergence.png'
set title 'Grid Convergence: CL at {/Symbol a}=2.50{/Symbol \260} (OAT15A M=0.73)'
set xlabel 'h = 1/{/Symbol \\326}N (characteristic cell size)'
set ylabel 'C_L'
set grid
set key top left
"""
    cols = []
    for i, s in enumerate(all_solvers):
        cols.append(f"'/app/plots/conv_data.dat' using 1:{i+2} with linespoints "
                    f"pt {i+4} ps 1.2 lw 2 title '{s.name}'")
    script += "plot " + ", \\\n     ".join(cols) + "\n"

    with open("/app/plots/convergence.gp", "w") as f:
        f.write(script)

    subprocess.run(["gnuplot", "/app/plots/convergence.gp"], check=True)


def generate_polar_plot(all_solvers, exp_alphas, exp_cls, exp_cds):
    """Generate gnuplot script and data for drag polar plot."""
    # Write experimental data
    with open("/app/plots/exp_polar.dat", "w") as f:
        f.write("# CD  CL\n")
        for cd, cl in zip(exp_cds, exp_cls):
            f.write(f"{cd:.6f}  {cl:.6f}\n")

    # Write solver data
    for s in all_solvers:
        with open(f"/app/plots/polar_{s.name}.dat", "w") as f:
            f.write("# CD  CL\n")
            for row in sorted(s.sweep, key=lambda x: x[2]):
                f.write(f"{row[4]:.6f}  {row[3]:.6f}\n")

    # Write gnuplot script
    script = """set terminal pngcairo size 900,600 enhanced font 'Arial,12'
set output '/app/plots/polar.png'
set title 'Drag Polar: OAT15A M=0.73 Re=3x10^6'
set xlabel 'C_D'
set ylabel 'C_L'
set grid
set key bottom right
"""
    plots = ["'/app/plots/exp_polar.dat' using 1:2 with linespoints "
             "pt 7 ps 1.5 lw 2 lc rgb 'black' title 'Experiment'"]
    colors = ['red', 'blue', 'green', 'orange', 'purple']
    for i, s in enumerate(all_solvers):
        plots.append(
            f"'/app/plots/polar_{s.name}.dat' using 1:2 with linespoints "
            f"pt {i+4} ps 1.0 lw 1.5 lc rgb '{colors[i]}' title '{s.name}'"
        )
    script += "plot " + ", \\\n     ".join(plots) + "\n"

    with open("/app/plots/polar.gp", "w") as f:
        f.write(script)

    subprocess.run(["gnuplot", "/app/plots/polar.gp"], check=True)


# ================================================================== #
#  Main Pipeline                                                       #
# ================================================================== #

def main():
    data_dir = "/app/data"

    # Parse experimental reference
    exp_alphas, exp_cls, exp_cds, exp_cms = parse_experiment(
        os.path.join(data_dir, "experiment.csv")
    )

    # Parse grid specification
    grid_spec = parse_grid_spec(os.path.join(data_dir, "grid_spec.csv"))

    # Parse all solver submissions
    solvers = [
        parse_tecplot(os.path.join(data_dir, "submission_fun3d_sa.dat"), "FUN3D_SA"),
        parse_csv_submission(os.path.join(data_dir, "submission_overflow_sst.csv"), "OVERFLOW_SST"),
        parse_fixed_width(os.path.join(data_dir, "submission_su2_sa.fwf"), "SU2_SA"),
        parse_jsonl(os.path.join(data_dir, "submission_tau_rsm.jsonl"), "TAU_RSM"),
        parse_tsv(os.path.join(data_dir, "submission_cfl3d_sa.tsv"), "CFL3D_SA"),
    ]

    print(f"Parsed {len(solvers)} solver submissions")
    for s in solvers:
        print(f"  {s.name}: {len(s.convergence)} convergence points, "
              f"{len(s.sweep)} sweep points")

    # Evaluate each solver
    results = {}
    r = 2.0  # uniform refinement ratio

    for solver in solvers:
        print(f"\nEvaluating {solver.name}...")

        # Detect anomalies and get clean convergence data
        has_anomaly, clean_conv = detect_anomaly(solver.convergence, r)

        if has_anomaly:
            print(f"  WARNING: Anomalous behavior detected in {solver.name}")

        # Sort convergence data by grid level (coarsest first)
        clean_conv_sorted = sorted(clean_conv, key=lambda x: x[0])

        # Richardson extrapolation for CL
        cl_pairs = [(1.0 / math.sqrt(row[1]), row[3]) for row in clean_conv_sorted]
        p_cl, extrap_cl = richardson_extrapolation(cl_pairs, r)

        # Richardson extrapolation for CD
        cd_pairs = [(1.0 / math.sqrt(row[1]), row[4]) for row in clean_conv_sorted]
        p_cd, extrap_cd = richardson_extrapolation(cd_pairs, r)

        # Average convergence order
        if math.isnan(p_cl):
            p_avg = p_cd
        elif math.isnan(p_cd):
            p_avg = p_cl
        else:
            p_avg = (p_cl + p_cd) / 2.0

        print(f"  Convergence order (CL): {p_cl:.3f}")
        print(f"  Convergence order (CD): {p_cd:.3f}")
        print(f"  Extrapolated CL: {extrap_cl:.6f}")
        print(f"  Extrapolated CD: {extrap_cd:.6f}")

        # Compute accuracy against experiment (alpha sweep at finest grid)
        sweep_sorted = sorted(solver.sweep, key=lambda x: x[2])

        # Match sweep alphas to experimental alphas
        pred_cls, pred_cds = [], []
        ref_cls, ref_cds = [], []
        for row in sweep_sorted:
            alpha = row[2]
            # Find matching experimental alpha
            for i, ea in enumerate(exp_alphas):
                if abs(ea - alpha) < 0.01:
                    pred_cls.append(row[3])
                    pred_cds.append(row[4])
                    ref_cls.append(exp_cls[i])
                    ref_cds.append(exp_cds[i])
                    break

        cl_rms = rms_error(pred_cls, ref_cls)
        cd_rms = rms_error(pred_cds, ref_cds)

        print(f"  CL RMS error: {cl_rms:.6f}")
        print(f"  CD RMS error: {cd_rms:.6f}")

        results[solver.name] = {
            "convergence_order": round(p_avg, 4),
            "converged_cl": round(extrap_cl, 6),
            "converged_cd": round(extrap_cd, 6),
            "cl_rms_error": round(cl_rms, 8),
            "cd_rms_error": round(cd_rms, 8),
            "anomaly": has_anomaly,
        }

    # Rank solvers by total error (CL RMS + CD RMS)
    ranked = sorted(
        results.keys(),
        key=lambda name: results[name]["cl_rms_error"] + results[name]["cd_rms_error"]
    )

    print(f"\nRanking (best to worst): {ranked}")

    # Assemble evaluation output
    evaluation = {
        "solvers": results,
        "ranking": ranked,
        "best_solver": ranked[0],
        "worst_solver": ranked[-1],
    }

    # Write evaluation JSON
    with open("/app/evaluation.json", "w") as f:
        json.dump(evaluation, f, indent=2)
    print(f"\nEvaluation written to /app/evaluation.json")

    # Generate gnuplot plots
    os.makedirs("/app/plots", exist_ok=True)
    generate_convergence_plot(solvers, grid_spec)
    print("Generated convergence plot: /app/plots/convergence.png")

    generate_polar_plot(solvers, exp_alphas, exp_cls, exp_cds)
    print("Generated drag polar plot: /app/plots/polar.png")

    print("\nDone.")


if __name__ == "__main__":
    main()
