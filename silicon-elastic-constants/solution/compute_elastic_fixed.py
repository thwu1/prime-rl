#!/usr/bin/env python3

"""
Corrected elastic constants computation for SW silicon via LAMMPS.

Fixes applied relative to the buggy /app/elastic_workflow/compute_elastic.py:
  1. BAR_TO_GPA: 1.01325e-4 (atm->GPa, wrong for metal units) -> 1.0e-4
     (bar->GPa, correct for LAMMPS metal units which report pressure in bars)
  2. Added energy minimization for shear strain perturbations (j >= 3).
     SW potential has 3-body angular terms so it is NOT a simple pair potential.
     Diamond-cubic Si has internal degrees of freedom (2-atom basis) that
     significantly affect shear elastic constants upon sublattice relaxation.
     Without relaxation, one obtains the Born (affine) C44 which is roughly
     double the relaxed value.
  3. Poisson ratio: single-crystal formula C12/(C11+C12) replaced with
     the polycrystalline Hill formula (3K-2G_H)/(2(3K+G_H))

Missing implementations added:
  4. Reuss shear modulus: G_R = 5(C11-C12)C44 / (4*C44 + 3*(C11-C12))
  5. E_111 via compliance tensor with orientation factor Gamma = 1/3 for [111]
  6. Cauchy pressure: C12 - C44
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

STRAIN = 1.0e-6
STRESS_LABELS = ["pxx", "pyy", "pzz", "pyz", "pxz", "pxy"]

# FIX 1: Correct conversion for LAMMPS metal units (bars -> GPa)
# 1 GPa = 10000 bar, so 1 bar = 1.0e-4 GPa
# The buggy code used 1.01325e-4 which is the atm->GPa factor (real units)
BAR_TO_GPA = 1.0e-4


def find_lammps():
    for name in ["lmp", "lmp_serial", "lmp_stable", "lmp_mpi"]:
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError("LAMMPS executable not found")


def run_lammps(script_content, label="run"):
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
    pattern = rf"^{re.escape(tag)}\s+([-+\d.eE]+)"
    for line in output.splitlines():
        m = re.match(pattern, line.strip())
        if m:
            return float(m.group(1))
    raise ValueError(f"Tag '{tag}' not found in output")


def parse_stresses(output):
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

# ── Apply +/- strains in 6 Voigt directions ──────────────────────
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

    # FIX 2: ALWAYS minimize after strain — SW has 3-body angular terms,
    # and diamond-cubic Si has internal degrees of freedom under shear.
    # Without relaxation, shear elastic constants reflect the Born (affine)
    # value which is roughly double the correct (relaxed) value.
    minimize_cmd = "minimize        1.0e-25 1.0e-25 50000 500000"

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

# ── Compute C_ij elastic constant tensor ──────────────────────────
print("Computing elastic constants...")

C = [[0.0] * 6 for _ in range(6)]
for j in range(6):
    for i in range(6):
        C[i][j] = -(stresses_pos[j][i] - stresses_neg[j][i]) / (2.0 * STRAIN)

for i in range(6):
    for j in range(6):
        C[i][j] *= BAR_TO_GPA

for i in range(6):
    for j in range(i + 1, 6):
        avg = 0.5 * (C[i][j] + C[j][i])
        C[i][j] = avg
        C[j][i] = avg

C11 = (C[0][0] + C[1][1] + C[2][2]) / 3.0
C12 = (C[0][1] + C[0][2] + C[1][2]) / 3.0
C44 = (C[3][3] + C[4][4] + C[5][5]) / 3.0

print(f"  C11 = {C11:.4f} GPa")
print(f"  C12 = {C12:.4f} GPa")
print(f"  C44 = {C44:.4f} GPa")

# ── Derive mechanical properties ──────────────────────────────────

K = (C11 + 2 * C12) / 3.0
G_V = (C11 - C12 + 3 * C44) / 5.0

# IMPL 4: Reuss shear modulus for cubic crystal
G_R = 5.0 * (C11 - C12) * C44 / (4 * C44 + 3 * (C11 - C12))

G_H = (G_V + G_R) / 2.0

E_100 = (C11 - C12) * (C11 + 2 * C12) / (C11 + C12)

# IMPL 5: E_111 from compliance tensor
denom_c = (C11 - C12) * (C11 + 2 * C12)
S11 = (C11 + C12) / denom_c
S12 = -C12 / denom_c
S44 = 1.0 / C44

# [111] direction: l_i = 1/sqrt(3)
# Gamma = l1^2*l2^2 + l2^2*l3^2 + l3^2*l1^2 = 3 * (1/3)^2 = 1/3
Gamma = 1.0 / 3.0
E_111 = 1.0 / (S11 - 2.0 * (S11 - S12 - 0.5 * S44) * Gamma)

# FIX 3: Polycrystalline Poisson ratio from Hill averages
nu = (3 * K - 2 * G_H) / (2 * (3 * K + G_H))

A = 2 * C44 / (C11 - C12)

# IMPL 6: Cauchy pressure
cauchy = C12 - C44

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
