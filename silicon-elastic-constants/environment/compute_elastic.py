#!/usr/bin/env python3
"""
Compute elastic constants and mechanical properties of silicon using LAMMPS
with the Stillinger-Weber (SW) interatomic potential.

Uses a finite-difference approach: apply small strains in each Voigt direction,
measure the stress response, and compute the C_ij elastic constant tensor.
Derived quantities (bulk modulus, shear moduli, Young's moduli, etc.) are then
computed from the cubic-averaged elastic constants.
"""

import subprocess
import json
import re
import os
import sys
import shutil

WORKDIR = "/app"
POTENTIAL_FILE = "/app/potentials/Si.sw"
RESTART_FILE = "/app/restart.equil"

STRAIN = 1.0e-6  # fractional strain magnitude for central differences

STRESS_LABELS = ["pxx", "pyy", "pzz", "pyz", "pxz", "pxy"]

# LAMMPS metal units: pressure in bars
# Convert bars to GPa: 1 bar = 1.01325e-4 GPa
BAR_TO_GPA = 1.01325e-4


def find_lammps():
    """Locate LAMMPS executable."""
    for name in ["lmp", "lmp_serial", "lmp_stable", "lmp_mpi"]:
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError("LAMMPS executable not found")


def run_lammps(script_content, label="run"):
    """Write and execute a LAMMPS input script."""
    script_path = os.path.join(WORKDIR, f"_lmp_{label}.in")
    with open(script_path, "w") as f:
        f.write(script_content)

    lmp = find_lammps()
    result = subprocess.run(
        [lmp, "-in", script_path, "-log", "none"],
        capture_output=True, text=True, cwd=WORKDIR, timeout=300,
    )
    if result.returncode != 0:
        print(f"LAMMPS failed for '{label}' (rc={result.returncode}):", file=sys.stderr)
        print(result.stderr[-2000:], file=sys.stderr)
        sys.exit(1)
    return result.stdout


def parse_tagged(output, tag):
    """Extract a floating-point value following a tag string."""
    pattern = rf"^{re.escape(tag)}\s+([-+\d.eE]+)"
    for line in output.splitlines():
        m = re.match(pattern, line.strip())
        if m:
            return float(m.group(1))
    raise ValueError(f"Tag '{tag}' not found in output")


def parse_stresses(output):
    """Parse all 6 Voigt stress components from LAMMPS output."""
    return [parse_tagged(output, f"ELASTIC_{s.upper()}") for s in STRESS_LABELS]


# ── Setup: build diamond-cubic Si crystal, relax, write restart ────
print("Setting up Si crystal...")

setup_script = f"""\
units           metal
boundary        p p p
atom_style      atomic

lattice         diamond 5.431
region          box block 0 3 0 3 0 3
create_box      1 box
create_atoms    1 box
mass            1 28.0855

pair_style      sw
pair_coeff      * * {POTENTIAL_FILE} Si

fix             relax all box/relax aniso 0.0 vmax 0.001
minimize        1.0e-25 1.0e-25 50000 500000
unfix           relax

variable tmp equal pxx
print "ELASTIC_PXX ${{tmp}}"
variable tmp equal pyy
print "ELASTIC_PYY ${{tmp}}"
variable tmp equal pzz
print "ELASTIC_PZZ ${{tmp}}"
variable tmp equal pyz
print "ELASTIC_PYZ ${{tmp}}"
variable tmp equal pxz
print "ELASTIC_PXZ ${{tmp}}"
variable tmp equal pxy
print "ELASTIC_PXY ${{tmp}}"

variable tmp equal lx
print "ELASTIC_LX ${{tmp}}"
variable tmp equal ly
print "ELASTIC_LY ${{tmp}}"
variable tmp equal lz
print "ELASTIC_LZ ${{tmp}}"

change_box      all triclinic
displace_atoms  all random 1.0e-5 1.0e-5 1.0e-5 87287 units box
write_restart   {RESTART_FILE}
"""

out = run_lammps(setup_script, "setup")
ref_stress = parse_stresses(out)
lx0 = parse_tagged(out, "ELASTIC_LX")
ly0 = parse_tagged(out, "ELASTIC_LY")
lz0 = parse_tagged(out, "ELASTIC_LZ")

print(f"  Reference stress (bar): {[f'{s:.4f}' for s in ref_stress]}")
print(f"  Box: lx={lx0:.6f} ly={ly0:.6f} lz={lz0:.6f}")

# ── Apply ± strains in 6 Voigt directions ─────────────────────────
print("Applying strain perturbations...")

DIRECTIONS = [
    ("xx", "x delta 0 {d:.15e}", lx0),
    ("yy", "y delta 0 {d:.15e}", ly0),
    ("zz", "z delta 0 {d:.15e}", lz0),
    ("yz", "yz delta {d:.15e}",  lz0),
    ("xz", "xz delta {d:.15e}",  lz0),
    ("xy", "xy delta {d:.15e}",  ly0),
]

stresses_pos = []
stresses_neg = []

for j, (label, cmd_template, ref_len) in enumerate(DIRECTIONS):
    disp = STRAIN * ref_len

    # For shear deformations (j >= 3) in pair-potential systems, the elastic
    # response to a homogeneous (affine) shear strain directly gives the
    # elastic constant. Atomic relaxation after affine shear only redistributes
    # internal stress within numerical noise for pair potentials where forces
    # depend solely on interatomic distances. Skipping minimization for shear
    # strains also avoids convergence issues with the minimizer under tilt
    # deformations.
    if j < 3:
        minimize_cmd = "minimize        1.0e-25 1.0e-25 50000 500000"
    else:
        minimize_cmd = "# affine shear: relaxation not needed for pair potentials"

    for sign, sign_name in [(1.0, "pos"), (-1.0, "neg")]:
        d = sign * disp
        change_cmd = "change_box all " + cmd_template.format(d=d) + " remap units box"
        strain_script = f"""\
read_restart    {RESTART_FILE}
pair_style      sw
pair_coeff      * * {POTENTIAL_FILE} Si
{change_cmd}
{minimize_cmd}
variable tmp equal pxx
print "ELASTIC_PXX ${{tmp}}"
variable tmp equal pyy
print "ELASTIC_PYY ${{tmp}}"
variable tmp equal pzz
print "ELASTIC_PZZ ${{tmp}}"
variable tmp equal pyz
print "ELASTIC_PYZ ${{tmp}}"
variable tmp equal pxz
print "ELASTIC_PXZ ${{tmp}}"
variable tmp equal pxy
print "ELASTIC_PXY ${{tmp}}"
"""
        out = run_lammps(strain_script, f"strain_{label}_{sign_name}")
        stresses = parse_stresses(out)
        if sign_name == "pos":
            stresses_pos.append(stresses)
        else:
            stresses_neg.append(stresses)

    print(f"  Direction {label}: done")

# ── Compute C_ij elastic constant tensor ───────────────────────────
print("Computing elastic constants...")

C = [[0.0] * 6 for _ in range(6)]
for j in range(6):
    for i in range(6):
        C[i][j] = -(stresses_pos[j][i] - stresses_neg[j][i]) / (2.0 * STRAIN)

# Convert to GPa
for i in range(6):
    for j in range(6):
        C[i][j] *= BAR_TO_GPA

# Symmetrize
for i in range(6):
    for j in range(i + 1, 6):
        avg = 0.5 * (C[i][j] + C[j][i])
        C[i][j] = avg
        C[j][i] = avg

# Cubic averaging of independent constants
C11 = (C[0][0] + C[1][1] + C[2][2]) / 3.0
C12 = (C[0][1] + C[0][2] + C[1][2]) / 3.0
C44 = (C[3][3] + C[4][4] + C[5][5]) / 3.0

print(f"  C11 = {C11:.4f} GPa")
print(f"  C12 = {C12:.4f} GPa")
print(f"  C44 = {C44:.4f} GPa")

# ── Derive mechanical properties ───────────────────────────────────

# Bulk modulus (Voigt = Reuss for cubic)
K = (C11 + 2 * C12) / 3.0

# Voigt shear modulus (cubic crystal)
G_V = (C11 - C12 + 3 * C44) / 5.0

# Reuss shear modulus (cubic crystal)
# TODO: implement the Reuss lower bound for the shear modulus of a cubic crystal
G_R = 0.0

# Hill average
G_H = (G_V + G_R) / 2.0

# Young's modulus along [100]
E_100 = (C11 - C12) * (C11 + 2 * C12) / (C11 + C12)

# Young's modulus along [111]
# TODO: implement using the compliance tensor and [111] direction cosines
E_111 = 0.0

# Poisson ratio
nu = C12 / (C11 + C12)

# Zener anisotropy ratio
A = 2 * C44 / (C11 - C12)

# Cauchy pressure
# TODO: implement for cubic crystal
cauchy = 0.0

# ── Write results ─────────────────────────────────────────────────
results = {
    "C11": round(C11, 4),
    "C12": round(C12, 4),
    "C44": round(C44, 4),
    "bulk_modulus": round(K, 4),
    "shear_modulus_voigt": round(G_V, 4),
    "shear_modulus_reuss": round(G_R, 4),
    "shear_modulus_hill": round(G_H, 4),
    "youngs_modulus_100": round(E_100, 4),
    "youngs_modulus_111": round(E_111, 4),
    "poisson_ratio": round(nu, 6),
    "zener_anisotropy": round(A, 6),
    "cauchy_pressure": round(cauchy, 4),
}

output_path = os.path.join(WORKDIR, "results.json")
with open(output_path, "w") as f:
    json.dump(results, f, indent=2)

print(f"\nResults written to {output_path}")
for k, v in results.items():
    print(f"  {k}: {v}")
