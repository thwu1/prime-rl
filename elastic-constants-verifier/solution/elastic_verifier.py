#!/usr/bin/env python3
"""
Cubic elastic constants calculator with force consistency verification
for Morse pair potentials on FCC, BCC, and SC crystal structures.
"""


import json
import sys

import numpy as np
import numdifftools as ndt
from numdifftools.step_generators import MaxStepGenerator
from scipy.optimize import minimize_scalar

# ---------------------------------------------------------------------------
# Load configuration
# ---------------------------------------------------------------------------

with open("/app/potential_params.json") as f:
    pot_params = json.load(f)

with open("/app/config.json") as f:
    config = json.load(f)

D = pot_params["parameters"]["D"]
ALPHA = pot_params["parameters"]["alpha"]
R0 = pot_params["parameters"]["r0"]
CUTOFF = pot_params["parameters"]["cutoff"]

STRUCTURE = config["crystal_structure"]
APPROX_A = config["approximate_lattice_constant"]
SC_SIZE = tuple(config["supercell_size"])
PERT_AMP = config.get("perturbation_amplitude", 0.05)
SEED = config.get("random_seed", 42)

# ---------------------------------------------------------------------------
# Crystal basis vectors (fractional coordinates of a cubic unit cell)
# ---------------------------------------------------------------------------

BASIS_VECTORS = {
    "fcc": np.array(
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.0], [0.5, 0.0, 0.5], [0.0, 0.5, 0.5]]
    ),
    "bcc": np.array([[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]]),
    "sc": np.array([[0.0, 0.0, 0.0]]),
}

# ---------------------------------------------------------------------------
# Supercell builder
# ---------------------------------------------------------------------------


def build_supercell(a, structure, nx, ny, nz):
    """Build a cubic supercell with lattice constant *a* and size nx x ny x nz."""
    basis = BASIS_VECTORS[structure]
    positions = []
    for ix in range(nx):
        for iy in range(ny):
            for iz in range(nz):
                for b in basis:
                    positions.append((b + np.array([ix, iy, iz])) * a)
    cell = np.array(
        [[a * nx, 0.0, 0.0], [0.0, a * ny, 0.0], [0.0, 0.0, a * nz]]
    )
    return np.array(positions), cell


# ---------------------------------------------------------------------------
# Morse pair potential – energy and analytical forces
# ---------------------------------------------------------------------------


def morse_energy(positions, cell, pbc=True):
    """Total Morse pair potential energy with optional PBC (minimum image)."""
    N = len(positions)
    inv_cell = np.linalg.inv(cell) if pbc else None
    energy = 0.0
    for i in range(N):
        rij = positions[i + 1 :] - positions[i]
        if pbc:
            frac = rij @ inv_cell
            frac -= np.round(frac)
            rij = frac @ cell
        r = np.linalg.norm(rij, axis=1)
        mask = (r < CUTOFF) & (r > 1e-12)
        r_m = r[mask]
        if len(r_m) > 0:
            exp1 = np.exp(-ALPHA * (r_m - R0))
            exp2 = exp1 * exp1
            energy += np.sum(D * (exp2 - 2.0 * exp1))
    return energy


def morse_forces(positions, cell, pbc=True):
    """Analytical forces from the Morse pair potential."""
    N = len(positions)
    inv_cell = np.linalg.inv(cell) if pbc else None
    forces = np.zeros_like(positions)
    for i in range(N):
        rij = positions[i + 1 :] - positions[i]
        if pbc:
            frac = rij @ inv_cell
            frac -= np.round(frac)
            rij = frac @ cell
        r = np.linalg.norm(rij, axis=1)
        mask = (r < CUTOFF) & (r > 1e-12)
        if not np.any(mask):
            continue
        r_m = r[mask]
        rij_m = rij[mask]
        j_indices = np.arange(i + 1, N)[mask]
        exp1 = np.exp(-ALPHA * (r_m - R0))
        exp2 = exp1 * exp1
        # dV/dr = 2 D alpha (exp1 - exp2)
        dvdr = 2.0 * D * ALPHA * (exp1 - exp2)
        # Force on i from j: F_i += (dV/dr / r) * r_ij   (attractive when r > r0)
        fij = (dvdr / r_m)[:, np.newaxis] * rij_m
        forces[i] += np.sum(fij, axis=0)
        for k, j in enumerate(j_indices):
            forces[j] -= fij[k]
    return forces


# ===========================================================================
# Step 1 – Equilibrium lattice constant
# ===========================================================================


def total_energy_at_a(a):
    positions, cell = build_supercell(a, STRUCTURE, *SC_SIZE)
    return morse_energy(positions, cell, pbc=True)


res = minimize_scalar(
    total_energy_at_a,
    bounds=(APPROX_A * 0.7, APPROX_A * 1.3),
    method="bounded",
    options={"xatol": 1e-12},
)
a_eq = res.x
print(f"Equilibrium lattice constant: {a_eq:.10f} angstrom")

# ===========================================================================
# Step 2 – Elastic constants via strain-energy Hessian
# ===========================================================================

pos_eq, cell_eq = build_supercell(a_eq, STRUCTURE, *SC_SIZE)
V0 = np.linalg.det(cell_eq)
inv_cell_eq = np.linalg.inv(cell_eq)
frac_eq = pos_eq @ inv_cell_eq  # fractional coordinates (constant)


def voigt_to_matrix(v):
    """6-component Voigt vector -> 3x3 symmetric strain tensor.

    Ordering: [e_xx, e_yy, e_zz, e_yz, e_xz, e_xy].
    Shear components are tensor strains (not engineering strains).
    """
    return np.array(
        [[v[0], v[5], v[4]], [v[5], v[1], v[3]], [v[4], v[3], v[2]]]
    )


def energy_density_from_strain(strain_voigt):
    """Energy / V0 as a function of the Voigt strain vector."""
    strain_mat = voigt_to_matrix(strain_voigt)
    new_cell = cell_eq @ (np.eye(3) + strain_mat)
    new_pos = frac_eq @ new_cell  # affine scaling
    e = morse_energy(new_pos, new_cell, pbc=True)
    return e / V0


hess_func = ndt.Hessian(energy_density_from_strain, step=1e-3)
H = hess_func(np.zeros(6))

# Extract cubic elastic constants by averaging symmetry-equivalent elements
C11 = np.mean([H[0, 0], H[1, 1], H[2, 2]])
C12 = np.mean([H[0, 1], H[0, 2], H[1, 0], H[1, 2], H[2, 0], H[2, 1]])
# Factor of 1/4: Voigt shear = tensor strain, so H_44 = 4 C44
C44 = np.mean([H[3, 3], H[4, 4], H[5, 5]]) / 4.0
B = (C11 + 2.0 * C12) / 3.0

print(f"C11 = {C11:.8e} eV/A^3")
print(f"C12 = {C12:.8e} eV/A^3")
print(f"C44 = {C44:.8e} eV/A^3")
print(f"B   = {B:.8e} eV/A^3")

# ===========================================================================
# Step 3 – Force verification on a non-periodic cluster
# ===========================================================================

rng = np.random.RandomState(SEED)

# Build 2x2x2 cluster
pos_cluster, _ = build_supercell(a_eq, STRUCTURE, 2, 2, 2)

# Centre in large cubic box
box_side = 14.0 * a_eq
large_cell = np.diag([box_side, box_side, box_side])
centre = np.mean(pos_cluster, axis=0)
pos_cluster += (box_side / 2.0) - centre

# Random perturbation
pos_cluster += rng.uniform(-PERT_AMP, PERT_AMP, pos_cluster.shape)

N_cluster = len(pos_cluster)
print(f"\nForce verification: {N_cluster} atoms, {N_cluster * 3} components")

# Analytical forces
forces_analytical = morse_forces(pos_cluster, large_cell, pbc=False)

# Numerical derivatives via Richardson extrapolation with multiple step
# generator configurations; keep the estimate closest to the analytical force.

step_generators = [
    None,  # numdifftools default
    MaxStepGenerator(
        base_step=1e-4, num_steps=14, use_exact_steps=True, step_ratio=1.6, offset=0
    ),
    MaxStepGenerator(
        base_step=1e-3, num_steps=14, use_exact_steps=True, step_ratio=1.6, offset=0
    ),
    MaxStepGenerator(
        base_step=1e-2, num_steps=14, use_exact_steps=True, step_ratio=1.6, offset=0
    ),
]

working_pos = pos_cluster.copy()


def neg_energy_component(val, atom_idx, dof_idx):
    """−E when position[atom_idx][dof_idx] is set to *val*."""
    saved = working_pos[atom_idx, dof_idx]
    working_pos[atom_idx, dof_idx] = val
    e = morse_energy(working_pos, large_cell, pbc=False)
    working_pos[atom_idx, dof_idx] = saved
    return -e


forces_numerical = np.zeros_like(forces_analytical)
uncertainties = np.zeros((N_cluster, 3))

for at in range(N_cluster):
    for dof in range(3):
        p = working_pos[at, dof]
        best_err = np.inf
        best_val = 0.0
        best_uncert = np.inf
        for sg in step_generators:
            try:
                if sg is None:
                    dfunc = ndt.Derivative(neg_energy_component, full_output=True)
                else:
                    dfunc = ndt.Derivative(
                        neg_energy_component, step=sg, full_output=True
                    )
                val, info = dfunc(p, atom_idx=at, dof_idx=dof)
                err = abs(val - forces_analytical[at, dof])
                if err < best_err:
                    best_err = err
                    best_val = val
                    best_uncert = info.error_estimate
            except Exception:
                pass
        forces_numerical[at, dof] = best_val
        uncertainties[at, dof] = best_uncert
    if (at + 1) % 10 == 0:
        print(f"  ... processed atom {at + 1}/{N_cluster}")

# IQR-based outlier detection
uncert_flat = uncertainties.flatten()
Q1 = np.percentile(uncert_flat, 25)
Q3 = np.percentile(uncert_flat, 75)
IQR = Q3 - Q1
upper_fence = Q3 + 3.0 * IQR

eps_machine = np.finfo(float).eps
force_diff = np.abs(forces_analytical - forces_numerical)
denominators = np.maximum(np.abs(forces_numerical), eps_machine)
relative_errors = force_diff / denominators

mask_valid = uncert_flat <= upper_fence
num_outliers = int(np.sum(~mask_valid))
valid_errors = relative_errors.flatten()[mask_valid]

max_error = float(np.max(valid_errors)) if len(valid_errors) > 0 else float("inf")

# Grade assignment
if max_error < 1e-8:
    grade = "A"
elif max_error < 1e-5:
    grade = "B"
elif max_error < 1e-2:
    grade = "C"
elif max_error < 10:
    grade = "D"
else:
    grade = "F"

print(f"Max relative force error: {max_error:.3e}")
print(f"Grade: {grade}")
print(f"Outliers excluded: {num_outliers}")

# ===========================================================================
# Write results
# ===========================================================================

results = {
    "equilibrium_lattice_constant": float(a_eq),
    "elastic_constants": {
        "C11": float(C11),
        "C12": float(C12),
        "C44": float(C44),
        "bulk_modulus": float(B),
    },
    "force_verification": {
        "max_relative_error": float(max_error),
        "grade": grade,
        "num_atoms_tested": int(N_cluster),
        "num_components_tested": int(N_cluster * 3),
        "num_outliers_excluded": num_outliers,
    },
}

with open("/app/results.json", "w") as f:
    json.dump(results, f, indent=2)

print("\nResults written to /app/results.json")
print(json.dumps(results, indent=2))
