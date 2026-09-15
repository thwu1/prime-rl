#!/usr/bin/env python3

"""
Solution: Fix three bugs in the Ewald summation pipeline, produce
validated results for both perfect and perturbed crystal configurations,
and evaluate reciprocal-space convergence.

Bug 1 (ewald_real.py): np.floor used instead of np.round for minimum image
Bug 2 (ewald_recip.py): reciprocal prefactor 2*pi/V instead of 4*pi/V
Bug 3 (run_pipeline.py): missing negative sign in Madelung extraction
"""

import sys
import os
import json

# ============================================================
# Step 1: Fix Bug 1 - minimum image convention (floor -> round)
# ============================================================
real_path = '/app/src/ewald_real.py'
with open(real_path) as f:
    code = f.read()
code = code.replace('np.floor(dr / L)', 'np.round(dr / L)')
with open(real_path, 'w') as f:
    f.write(code)

# ============================================================
# Step 2: Fix Bug 2 - reciprocal prefactor (2*pi -> 4*pi)
# ============================================================
recip_path = '/app/src/ewald_recip.py'
with open(recip_path) as f:
    code = f.read()
code = code.replace(
    'pref_const = 2.0 * np.pi / V',
    'pref_const = 4.0 * np.pi / V'
)
with open(recip_path, 'w') as f:
    f.write(code)

# ============================================================
# Step 3: Fix Bug 3 - Madelung sign (add negative)
# ============================================================
pipeline_path = '/app/run_pipeline.py'
with open(pipeline_path) as f:
    code = f.read()
code = code.replace(
    'return 2.0 * total_energy * d / n_particles',
    'return -2.0 * total_energy * d / n_particles'
)
with open(pipeline_path, 'w') as f:
    f.write(code)

# ============================================================
# Step 4: Run corrected pipeline and produce full results
# ============================================================
sys.path.insert(0, '/app')

import numpy as np
from src.ewald_real import compute_real_space
from src.ewald_recip import compute_reciprocal
from src.ewald_self import compute_self_energy
from src.io_utils import load_system, load_parameters

params = load_parameters('/app/data/params.ini')
alpha = params['alpha']
k_max = params['k_max']

# --- Perfect crystal ---
crystal = load_system('/app/data/nacl_crystal.npz')
E_real_c, F_real_c = compute_real_space(
    crystal['positions'], crystal['charges'], crystal['box_length'], alpha
)
E_recip_c, F_recip_c = compute_reciprocal(
    crystal['positions'], crystal['charges'], crystal['box_length'], alpha, k_max
)
E_self_c = compute_self_energy(crystal['charges'], alpha)
E_total_c = E_real_c + E_recip_c + E_self_c
F_total_c = F_real_c + F_recip_c

madelung = -2.0 * E_total_c * crystal['d'] / crystal['n_particles']
max_force = float(np.max(np.linalg.norm(F_total_c, axis=1)))

print(f"Madelung constant: {madelung:.10f} (ref: 1.7475645946)")
print(f"Max crystal force: {max_force:.2e}")

# --- Perturbed crystal ---
perturbed = load_system('/app/data/perturbed_crystal.npz')
E_real_p, F_real_p = compute_real_space(
    perturbed['positions'], perturbed['charges'], perturbed['box_length'], alpha
)
E_recip_p, F_recip_p = compute_reciprocal(
    perturbed['positions'], perturbed['charges'], perturbed['box_length'], alpha, k_max
)
E_self_p = compute_self_energy(perturbed['charges'], alpha)
E_total_p = E_real_p + E_recip_p + E_self_p
F_total_p = F_real_p + F_recip_p
force_sum = np.sum(F_total_p, axis=0).tolist()

print(f"Perturbed energy: {E_total_p:.10f}")
print(f"Force sum: [{force_sum[0]:.2e}, {force_sum[1]:.2e}, {force_sum[2]:.2e}]")

# --- Finite difference check on particle 0 ---
dx = 1e-5
L = perturbed['box_length']

pos_plus = perturbed['positions'].copy()
pos_plus[0, 0] = (pos_plus[0, 0] + dx) % L
E_r_plus, _ = compute_real_space(pos_plus, perturbed['charges'], L, alpha)
E_k_plus, _ = compute_reciprocal(pos_plus, perturbed['charges'], L, alpha, k_max)
E_s_plus = compute_self_energy(perturbed['charges'], alpha)
E_plus = E_r_plus + E_k_plus + E_s_plus

pos_minus = perturbed['positions'].copy()
pos_minus[0, 0] = (pos_minus[0, 0] - dx) % L
E_r_minus, _ = compute_real_space(pos_minus, perturbed['charges'], L, alpha)
E_k_minus, _ = compute_reciprocal(pos_minus, perturbed['charges'], L, alpha, k_max)
E_s_minus = compute_self_energy(perturbed['charges'], alpha)
E_minus = E_r_minus + E_k_minus + E_s_minus

numerical_fx = -(E_plus - E_minus) / (2.0 * dx)
analytical_fx = float(F_total_p[0, 0])
if abs(analytical_fx) > 1e-10:
    rel_err = abs(numerical_fx - analytical_fx) / abs(analytical_fx)
else:
    rel_err = abs(numerical_fx - analytical_fx)
print(f"FD check: analytical={analytical_fx:.10f}, numerical={numerical_fx:.10f}, "
      f"rel_err={rel_err:.2e}")

# ============================================================
# Step 5: Convergence study - evaluate reciprocal-space cutoff
# ============================================================
print("\n--- Convergence Study ---")
ref_madelung = 1.7475645946
convergence_study = []

# Real-space and self-energy are independent of k_max
for km in [3, 4, 5, 6, 7, 8, 9]:
    E_recip_km, _ = compute_reciprocal(
        crystal['positions'], crystal['charges'], crystal['box_length'], alpha, km
    )
    E_total_km = E_real_c + E_recip_km + E_self_c
    M_km = -2.0 * E_total_km * crystal['d'] / crystal['n_particles']
    error = abs(M_km - ref_madelung)
    convergence_study.append({"k_max": km, "madelung": float(M_km)})
    print(f"  k_max={km}: M={M_km:.10f}, error={error:.2e}")

# Determine minimum converged k_max
min_converged_k_max = None
for entry in convergence_study:
    if abs(entry["madelung"] - ref_madelung) < 1e-3:
        min_converged_k_max = entry["k_max"]
        break

print(f"  min_converged_k_max = {min_converged_k_max}")

# --- Write results ---
result = {
    "nacl_madelung": float(madelung),
    "nacl_max_force": float(max_force),
    "perturbed_energy": float(E_total_p),
    "perturbed_energy_components": {
        "real": float(E_real_p),
        "recip": float(E_recip_p),
        "self": float(E_self_p)
    },
    "perturbed_forces": F_total_p.tolist(),
    "perturbed_force_sum": force_sum,
    "fd_check": {
        "dx": dx,
        "energy_plus": float(E_plus),
        "energy_minus": float(E_minus),
        "numerical_force_x": float(numerical_fx)
    },
    "convergence_study": convergence_study,
    "min_converged_k_max": min_converged_k_max
}

with open('/app/result.json', 'w') as f:
    json.dump(result, f, indent=2)

print("\nResults written to /app/result.json")
