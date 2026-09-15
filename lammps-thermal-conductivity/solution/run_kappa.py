#!/usr/bin/env python3
"""
Fix buggy LAMMPS thermal conductivity scripts and produce correct results.

Bug 1 (in.heat): The kappa variable formula uses energy rate 10.0 but fix heat
    injects 100.0 per timestep. Fix: change 10.0 -> 100.0 in the formula.

Bug 2 (in.mp): (a) Temperature difference sign is wrong: f_2[1][3]-f_2[11][3]
    should be f_2[11][3]-f_2[1][3] since chunk 11 (center) is hot. (b) The fix
    thermal/conductivity energy accumulator is not reset before the production
    run, so f_3 includes equilibration energy. Fix: redefine fix 3 before
    production to reset the accumulator.
"""

import json
import math
import os
import re
import shutil
import subprocess
import sys

# ---------------------------------------------------------------------------
# Corrected LAMMPS input scripts
# ---------------------------------------------------------------------------

HEAT_SCRIPT_FIXED = """\
# Thermal conductivity of LJ fluid via fix heat NEMD method (CORRECTED)
# System: 8000 atoms, rho*=0.6, T*=1.35, rc=2.5sigma

variable        x equal 10
variable        y equal 10
variable        z equal 20
variable        rho equal 0.6
variable        t equal 1.35
variable        rc equal 2.5

units           lj
atom_style      atomic

lattice         fcc ${rho}
region          box block 0 $x 0 $y 0 $z
create_box      1 box
create_atoms    1 box
mass            1 1.0

velocity        all create $t 87287

pair_style      lj/cut ${rc}
pair_coeff      1 1 1.0 1.0

neighbor        0.3 bin
neigh_modify    delay 0 every 1

region          hot block INF INF INF INF 0 1
region          cold block INF INF INF INF 10 11
compute         Thot all temp/region hot
compute         Tcold all temp/region cold

fix             1 all nvt temp $t $t 0.5
thermo          100
run             1000

velocity        all scale $t
unfix           1

fix             1 all nve
fix             hot all heat 1 100.0 region hot
fix             cold all heat 1 -100.0 region cold

thermo_style    custom step temp c_Thot c_Tcold
thermo          1000
run             10000

compute         ke all ke/atom
variable        temp atom c_ke/1.5

compute         layers all chunk/atom bin/1d z lower 0.05 units reduced
fix             2 all ave/chunk 10 100 1000 layers v_temp file profile.heat

variable        tdiff equal f_2[1][3]-f_2[11][3]
fix             ave all ave/time 1 1 1000 v_tdiff ave running start 13000

# FIX: energy rate must match fix heat value (100.0, not 10.0)
variable        kappa equal (100.0/(lx*ly)/2.0)*(lz/2.0)/f_ave

thermo_style    custom step temp c_Thot c_Tcold v_tdiff f_ave
thermo          1000
run             20000
print           "KAPPA_HEAT $(v_kappa:%.6f)"
"""

MP_SCRIPT_FIXED = """\
# Thermal conductivity of LJ fluid via Muller-Plathe method (CORRECTED)
# System: 8000 atoms, rho*=0.6, T*=1.35, rc=2.5sigma

variable        x equal 10
variable        y equal 10
variable        z equal 20
variable        rho equal 0.6
variable        t equal 1.35
variable        rc equal 2.5

units           lj
atom_style      atomic

lattice         fcc ${rho}
region          box block 0 $x 0 $y 0 $z
create_box      1 box
create_atoms    1 box
mass            1 1.0

velocity        all create $t 87287

pair_style      lj/cut ${rc}
pair_coeff      1 1 1.0 1.0

neighbor        0.3 bin
neigh_modify    delay 0 every 1

fix             1 all nvt temp $t $t 0.5
thermo          100
run             1000

velocity        all scale $t
unfix           1

compute         ke all ke/atom
variable        temp atom c_ke/1.5

fix             1 all nve

compute         layers all chunk/atom bin/1d z lower 0.05 units reduced
fix             2 all ave/chunk 10 100 1000 layers v_temp file profile.mp
fix             3 all thermal/conductivity 10 z 20

# FIX: correct sign — chunk 11 (center) is hot, chunk 1 (edge) is cold
variable        tdiff equal f_2[11][3]-f_2[1][3]
thermo_style    custom step temp epair etotal f_3 v_tdiff
thermo          1000
run             20000

# FIX: reset fix thermal/conductivity to zero energy accumulation
fix             3 all thermal/conductivity 10 z 20

variable        start_time equal time

variable        kappa equal (f_3/(time-${start_time})/(lx*ly)/2.0)*(lz/2.0)/f_ave

fix             ave all ave/time 1 1 1000 v_tdiff ave running
thermo_style    custom step temp epair etotal f_3 v_tdiff f_ave
thermo          1000
run             20000
print           "KAPPA_MP $(v_kappa:%.6f)"
"""


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def find_lmp():
    """Locate the LAMMPS binary on the system."""
    for cmd in ["lmp", "lmp_serial", "lammps", "lmp_mpi"]:
        if shutil.which(cmd):
            return cmd
    raise RuntimeError(
        "LAMMPS binary not found. Tried: lmp, lmp_serial, lammps, lmp_mpi"
    )


def run_lammps(lmp_bin, input_file, log_file):
    """Run a LAMMPS simulation, returning combined stdout + log content."""
    result = subprocess.run(
        [lmp_bin, "-in", input_file, "-log", log_file],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if result.returncode != 0:
        print(f"ERROR running {input_file}:", file=sys.stderr)
        print(result.stderr[-2000:], file=sys.stderr)
        sys.exit(1)

    log_path = os.path.join("/app", log_file)
    log_text = ""
    if os.path.exists(log_path):
        with open(log_path) as f:
            log_text = f.read()
    return result.stdout + "\n" + log_text


def extract_kappa(text, label):
    """Extract kappa value from LAMMPS output by searching for a labelled line."""
    pattern = rf"{label}\s+([-+\d.eE]+)"
    matches = re.findall(pattern, text)
    if not matches:
        raise ValueError(f"Could not find '{label}' in LAMMPS output")
    return float(matches[-1])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    lmp = find_lmp()
    print(f"Using LAMMPS binary: {lmp}")

    # Write corrected input scripts (overwriting buggy originals)
    with open("/app/in.heat", "w") as f:
        f.write(HEAT_SCRIPT_FIXED)
    with open("/app/in.mp", "w") as f:
        f.write(MP_SCRIPT_FIXED)

    # Run corrected simulations
    print("=== Running corrected fix-heat NEMD simulation ===")
    out_heat = run_lammps(lmp, "in.heat", "log.heat")

    print("=== Running corrected Muller-Plathe simulation ===")
    out_mp = run_lammps(lmp, "in.mp", "log.mp")

    # Parse kappa from each simulation
    kappa_heat = extract_kappa(out_heat, "KAPPA_HEAT")
    kappa_mp = extract_kappa(out_mp, "KAPPA_MP")

    print(f"kappa (fix heat)       = {kappa_heat:.4f} [LJ units]")
    print(f"kappa (Muller-Plathe)  = {kappa_mp:.4f} [LJ units]")

    kappa_avg = (kappa_heat + kappa_mp) / 2.0

    # --- Argon LJ parameters ---
    kB = 1.380649e-23       # J/K  (2019 SI exact)
    eps_over_kB = 119.8     # K
    sigma = 3.405e-10       # m
    mass_amu = 39.948
    amu_to_kg = 1.66054e-27

    epsilon = eps_over_kB * kB          # J
    mass = mass_amu * amu_to_kg         # kg
    tau = sigma * math.sqrt(mass / epsilon)  # s

    # Convert kappa: kappa_SI = kappa_LJ * kB / (sigma * tau)
    kappa_si = kappa_avg * kB / (sigma * tau)

    results = {
        "kappa_method1": round(kappa_heat, 6),
        "kappa_method2": round(kappa_mp, 6),
        "kappa_avg_lj": round(kappa_avg, 6),
        "kappa_si": kappa_si,
        "argon_params": {
            "epsilon_J": epsilon,
            "sigma_m": sigma,
            "mass_kg": mass,
            "tau_s": tau,
        },
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults written to /app/results.json")
    print(f"kappa_avg  = {kappa_avg:.4f} [LJ]")
    print(f"kappa_SI   = {kappa_si:.6f} W/(m*K)")
    print(f"tau        = {tau:.6e} s")


if __name__ == "__main__":
    main()
