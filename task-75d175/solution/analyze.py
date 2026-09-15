#!/usr/bin/env python3
"""
Mesh convergence study for the lid-driven cavity at Re=100.

Runs the corrected case at three mesh refinement levels, extracts vertical
centerline u-velocity profiles, performs Richardson extrapolation at Ghia
et al. (1982) reference y-coordinates, computes the observed order of
convergence and Grid Convergence Index, and writes a JSON report.
"""

import json
import math
import os
import re
import shutil
import subprocess

CASE_DIR = "/app/cavity"
REPORT_PATH = "/app/convergence_report.json"
MESH_LEVELS = [20, 40, 80]
REFINEMENT_RATIO = 2.0
SAFETY_FACTOR = 1.25
CAVITY_LENGTH = 0.1

# Ghia et al. (1982) Re=100 reference: u along vertical centerline (x=0.5)
GHIA_REFERENCE = {
    0.9766: 0.84123,
    0.5000: -0.20581,
    0.2813: -0.15662,
    0.1016: -0.06434,
    0.0547: -0.03717,
}

SAMPLE_Y = sorted(GHIA_REFERENCE.keys())

# Very tight solver settings to ensure iterative error is negligible
# compared to discretization error, producing clean monotone mesh convergence.
TIGHT_FVSOLUTION = """\
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSolution;
}

solvers
{
    p
    {
        solver          GAMG;
        tolerance       1e-10;
        relTol          0;
        smoother        DICGaussSeidel;
    }

    U
    {
        solver          PBiCGStab;
        preconditioner  DILU;
        tolerance       1e-10;
        relTol          0;
    }
}

SIMPLE
{
    nNonOrthogonalCorrectors 0;
    pRefCell        0;
    pRefValue       0;

    residualControl
    {
        p               1e-8;
        U               1e-8;
    }
}

relaxationFactors
{
    fields
    {
        p               0.3;
    }
    equations
    {
        U               0.7;
    }
}
"""

TIGHT_CONTROLDICT = """\
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      controlDict;
}

application     simpleFoam;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         5000;
deltaT          1;
writeControl    timeStep;
writeInterval   5000;
purgeWrite      0;
writeFormat     ascii;
writePrecision  10;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable true;
"""


def clean_case():
    """Remove polyMesh, time directories, and logs."""
    for item in os.listdir(CASE_DIR):
        full = os.path.join(CASE_DIR, item)
        if os.path.isdir(full):
            try:
                t = float(item)
                if t > 0:
                    shutil.rmtree(full)
                    continue
            except ValueError:
                pass
            if item.startswith("processor") or item == "postProcessing":
                shutil.rmtree(full)
            elif item == "constant":
                polymesh = os.path.join(full, "polyMesh")
                if os.path.isdir(polymesh):
                    shutil.rmtree(polymesh)
        elif item.startswith("log."):
            os.remove(full)


def set_mesh_resolution(n):
    """Rewrite the blocks line in blockMeshDict to use n x n x 1 cells."""
    path = os.path.join(CASE_DIR, "system", "blockMeshDict")
    with open(path) as f:
        content = f.read()
    content = re.sub(
        r"hex\s*\([^)]+\)\s*\(\s*\d+\s+\d+\s+1\s*\)",
        f"hex (0 1 2 3 4 5 6 7) ({n} {n} 1)",
        content,
    )
    with open(path, "w") as f:
        f.write(content)


def run_openfoam():
    """Run blockMesh followed by simpleFoam.  Returns True on success."""
    cmd = (
        ". /usr/lib/openfoam/openfoam2312/etc/bashrc 2>/dev/null && "
        "cd /app/cavity && "
        "blockMesh > log.blockMesh 2>&1 && "
        "simpleFoam > log.simpleFoam 2>&1"
    )
    env = os.environ.copy()
    env["FOAM_SIGFPE"] = "false"
    result = subprocess.run(["bash", "-c", cmd], env=env)
    return result.returncode == 0


def latest_time_dir():
    """Return the name of the latest positive-time directory, or None."""
    best = None
    for d in os.listdir(CASE_DIR):
        full = os.path.join(CASE_DIR, d)
        if not os.path.isdir(full):
            continue
        try:
            t = float(d)
            if t > 0 and (best is None or t > best[0]):
                best = (t, d)
        except ValueError:
            pass
    return best[1] if best else None


def parse_vector_field(filepath):
    """Parse an OpenFOAM volVectorField and return [(ux, uy, uz), ...]."""
    with open(filepath) as f:
        content = f.read()

    # Uniform field
    m = re.search(r"internalField\s+uniform\s+\(([^)]+)\)", content)
    if m:
        vals = list(map(float, m.group(1).split()))
        return [tuple(vals)]

    # Non-uniform list
    m = re.search(
        r"internalField\s+nonuniform\s+List<vector>\s*\n\s*(\d+)\s*\n\s*\(",
        content,
    )
    if not m:
        raise ValueError(f"Cannot parse internalField in {filepath}")

    n_cells = int(m.group(1))
    block = content[m.end():]
    end = block.find("\n)\n")
    if end == -1:
        end = block.find(")\n;")
    if end == -1:
        end = len(block)
    vectors_text = block[:end]

    vectors = []
    for tok in re.findall(r"\(([^)]+)\)", vectors_text):
        parts = tok.split()
        if len(parts) == 3:
            vectors.append(tuple(map(float, parts)))

    if len(vectors) != n_cells:
        raise ValueError(
            f"Expected {n_cells} vectors, parsed {len(vectors)} in {filepath}"
        )
    return vectors


def extract_centerline_u(n):
    """Extract interpolated u-velocity along x=L/2 for an n x n mesh.

    Returns {y_normalized: u_velocity} for each SAMPLE_Y coordinate.
    """
    td = latest_time_dir()
    if td is None:
        raise RuntimeError("No time directory found")

    vectors = parse_vector_field(os.path.join(CASE_DIR, td, "U"))
    if len(vectors) != n * n:
        raise RuntimeError(
            f"Expected {n*n} cells, got {len(vectors)}"
        )

    dx = CAVITY_LENGTH / n
    x_center = CAVITY_LENGTH / 2.0

    # Two columns bracketing x = L/2
    i_left = int(x_center / dx - 0.5)
    i_right = i_left + 1
    if i_right >= n:
        i_right = n - 1

    x_left = (i_left + 0.5) * dx
    x_right = (i_right + 0.5) * dx
    denom = x_right - x_left
    wx = (x_center - x_left) / denom if abs(denom) > 1e-15 else 0.5

    # Build the centerline profile (y_norm, u_interp)
    profile_y = []
    profile_u = []
    for j in range(n):
        y_norm = ((j + 0.5) * dx) / CAVITY_LENGTH
        ux_l = vectors[i_left + j * n][0]
        ux_r = vectors[i_right + j * n][0]
        profile_y.append(y_norm)
        profile_u.append(ux_l * (1 - wx) + ux_r * wx)

    # Interpolate to each sample y-coordinate
    results = {}
    for y_target in SAMPLE_Y:
        if y_target <= profile_y[0]:
            results[y_target] = profile_u[0]
        elif y_target >= profile_y[-1]:
            results[y_target] = profile_u[-1]
        else:
            for k in range(len(profile_y) - 1):
                if profile_y[k] <= y_target <= profile_y[k + 1]:
                    t = (y_target - profile_y[k]) / (
                        profile_y[k + 1] - profile_y[k]
                    )
                    results[y_target] = (
                        profile_u[k] * (1 - t) + profile_u[k + 1] * t
                    )
                    break
    return results


def richardson_extrapolation(f1, f2, f3, r):
    """Richardson extrapolation from three grid levels.

    f1 = coarsest, f2 = medium, f3 = finest.
    Returns (f_extrapolated, observed_order, gci_fine).
    """
    eps_21 = f2 - f1
    eps_32 = f3 - f2

    if abs(eps_32) < 1e-15 or abs(eps_21) < 1e-15:
        return f3, 2.0, 0.0

    ratio = eps_21 / eps_32
    if ratio <= 0:
        # Oscillatory convergence — assume second-order
        p = 2.0
    else:
        p = math.log(ratio) / math.log(r)
        p = max(0.5, min(p, 4.0))

    rp = r ** p
    f_ext = f3 + eps_32 / (rp - 1)

    # Relative GCI
    if abs(f3) > 1e-15:
        gci = SAFETY_FACTOR * abs((f3 - f2) / f3) / (rp - 1)
    else:
        gci = SAFETY_FACTOR * abs(f3 - f2) / (rp - 1)

    return f_ext, p, gci


def main():
    mesh_data = {}  # n -> {y_norm: u}

    # Save original system files so we can restore after the study
    saved_files = {}
    for name in ["blockMeshDict", "fvSolution", "controlDict"]:
        path = os.path.join(CASE_DIR, "system", name)
        with open(path) as f:
            saved_files[name] = f.read()

    # Write tight solver settings for accurate convergence study
    with open(os.path.join(CASE_DIR, "system", "fvSolution"), "w") as f:
        f.write(TIGHT_FVSOLUTION)
    with open(os.path.join(CASE_DIR, "system", "controlDict"), "w") as f:
        f.write(TIGHT_CONTROLDICT)

    try:
        for n in MESH_LEVELS:
            print(f"\n=== Mesh {n}x{n} ===")
            clean_case()
            set_mesh_resolution(n)

            ok = run_openfoam()
            if not ok:
                log = os.path.join(CASE_DIR, "log.simpleFoam")
                if os.path.exists(log):
                    with open(log) as f:
                        tail = f.readlines()[-15:]
                    print("".join(tail))
                raise RuntimeError(f"Simulation failed at {n}x{n}")

            mesh_data[n] = extract_centerline_u(n)
            print(f"  Centerline data: { {y: round(u,5) for y,u in mesh_data[n].items()} }")
    finally:
        # Restore original system files
        for name, content in saved_files.items():
            path = os.path.join(CASE_DIR, "system", name)
            with open(path, "w") as f:
                f.write(content)

    # ── Richardson extrapolation at each sample point ──
    sample_points = []
    all_asymptotic = True

    for y in SAMPLE_Y:
        u_c = mesh_data[MESH_LEVELS[0]].get(y)
        u_m = mesh_data[MESH_LEVELS[1]].get(y)
        u_f = mesh_data[MESH_LEVELS[2]].get(y)

        if u_c is None or u_m is None or u_f is None:
            print(f"WARNING: missing data at y={y}")
            continue

        u_ext, p, gci_fine = richardson_extrapolation(
            u_c, u_m, u_f, REFINEMENT_RATIO
        )

        # Asymptotic-range check: |eps_21| / (r^p * |eps_32|) ~ 1
        eps_21 = u_m - u_c
        eps_32 = u_f - u_m
        if abs(eps_32) > 1e-15:
            ar = abs(eps_21) / (REFINEMENT_RATIO ** p * abs(eps_32))
            if abs(ar - 1.0) > 0.15:
                all_asymptotic = False
        # else: effectively converged — counts as asymptotic

        sample_points.append({
            "y_normalized": y,
            "u_coarse": round(u_c, 8),
            "u_medium": round(u_m, 8),
            "u_fine": round(u_f, 8),
            "u_extrapolated": round(u_ext, 8),
            "u_ghia": GHIA_REFERENCE[y],
            "observed_order": round(p, 4),
            "gci_fine": round(gci_fine, 8),
        })

    report = {
        "mesh_levels": MESH_LEVELS,
        "refinement_ratio": REFINEMENT_RATIO,
        "sample_points": sample_points,
        "asymptotic_range": all_asymptotic,
    }

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nReport written to {REPORT_PATH}")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
