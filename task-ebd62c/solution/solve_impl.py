#!/usr/bin/env python3
"""
Solution: fix build system, repair C-Python interface, implement analysis pipeline.
"""

import subprocess
import os
import sys

# ============================================================
# Step 1: Fix Makefile — add -lm for math library linking
# ============================================================
makefile_path = '/app/Makefile'
with open(makefile_path, 'r') as f:
    content = f.read()

content = content.replace(
    '$(CC) $(CFLAGS) $(LDFLAGS) -o $@ src/elastic_core.c',
    '$(CC) $(CFLAGS) $(LDFLAGS) -o $@ src/elastic_core.c -lm',
)
with open(makefile_path, 'w') as f:
    f.write(content)
print("Step 1: Fixed Makefile — added -lm linker flag")

# ============================================================
# Step 2: Build C shared library
# ============================================================
subprocess.check_call(['make', '-C', '/app'], timeout=60)
print("Step 2: Built libfem_core.so")

# ============================================================
# Step 3: Write corrected buckling_analysis.py
#         - Fix ctypes ref_vec binding
#         - Implement all five stub functions
# ============================================================

CORRECTED_CODE = r'''"""
3D Frame Eigenvalue Buckling Analysis — Complete Implementation

Mixed C/Python implementation. Core matrix operations (elastic stiffness,
coordinate transformation) are in C (/app/libfem_core.so). The stability
analysis pipeline (geometric stiffness, eigenvalue solve) is in Python.
"""

import ctypes
import os
import numpy as np
import scipy.linalg
from ctypes import c_double, POINTER
from typing import Sequence


# ---------------------------------------------------------------------------
#  C Library Interface
# ---------------------------------------------------------------------------

_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libfem_core.so')
_lib = ctypes.CDLL(_lib_path)

_lib.local_elastic_stiffness_3D_c.argtypes = [
    c_double, c_double, c_double, c_double,
    c_double, c_double, c_double,
    POINTER(c_double),
]
_lib.local_elastic_stiffness_3D_c.restype = None

_lib.transformation_matrix_3D_c.argtypes = [
    c_double, c_double, c_double,
    c_double, c_double, c_double,
    POINTER(c_double),
    POINTER(c_double),
]
_lib.transformation_matrix_3D_c.restype = None


# ---------------------------------------------------------------------------
#  Utility
# ---------------------------------------------------------------------------

def _node_dofs(n: int) -> list[int]:
    base = 6 * n
    return [base + i for i in range(6)]


# ---------------------------------------------------------------------------
#  Elastic stiffness (via C library)
# ---------------------------------------------------------------------------

def local_elastic_stiffness_3D(E, nu, A, L, Iy, Iz, J):
    k = np.zeros((12, 12), dtype=np.float64, order='C')
    _lib.local_elastic_stiffness_3D_c(
        c_double(E), c_double(nu), c_double(A), c_double(L),
        c_double(Iy), c_double(Iz), c_double(J),
        k.ctypes.data_as(POINTER(c_double)),
    )
    return k


# ---------------------------------------------------------------------------
#  Transformation matrix (via C library) — FIXED: properly pass ref_vec
# ---------------------------------------------------------------------------

def transformation_matrix_3D(x1, y1, z1, x2, y2, z2, ref_vec=None):
    Gamma = np.zeros((12, 12), dtype=np.float64, order='C')
    if ref_vec is not None:
        _ref = np.asarray(ref_vec, dtype=np.float64).copy()
        _ref_ptr = _ref.ctypes.data_as(POINTER(c_double))
    else:
        _ref_ptr = None
    _lib.transformation_matrix_3D_c(
        c_double(x1), c_double(y1), c_double(z1),
        c_double(x2), c_double(y2), c_double(z2),
        _ref_ptr,
        Gamma.ctypes.data_as(POINTER(c_double)),
    )
    return Gamma


# ---------------------------------------------------------------------------
#  Global elastic assembly
# ---------------------------------------------------------------------------

def assemble_elastic_stiffness(node_coords, elements):
    n_nodes = node_coords.shape[0]
    n_dof = 6 * n_nodes
    K = np.zeros((n_dof, n_dof))
    for ele in elements:
        ni, nj = int(ele['node_i']), int(ele['node_j'])
        xi, yi, zi = node_coords[ni]
        xj, yj, zj = node_coords[nj]
        L = np.linalg.norm([xj - xi, yj - yi, zj - zi])
        Gamma = transformation_matrix_3D(
            xi, yi, zi, xj, yj, zj, ele.get('local_z')
        )
        k_loc = local_elastic_stiffness_3D(
            ele['E'], ele['nu'], ele['A'], L,
            ele['I_y'], ele['I_z'], ele['J']
        )
        k_glb = Gamma.T @ k_loc @ Gamma
        dofs = _node_dofs(ni) + _node_dofs(nj)
        K[np.ix_(dofs, dofs)] += k_glb
    return K


def assemble_load_vector(nodal_loads, n_nodes):
    n_dof = 6 * n_nodes
    P = np.zeros(n_dof)
    for n, load in nodal_loads.items():
        P[_node_dofs(n)] += np.asarray(load, dtype=float)
    return P


# ---------------------------------------------------------------------------
#  DOF partitioning and linear solve
# ---------------------------------------------------------------------------

def partition_dofs(boundary_conditions, n_nodes):
    n_dof = n_nodes * 6
    fixed = []
    for n in range(n_nodes):
        flags = boundary_conditions.get(n)
        if flags is not None:
            fixed.extend([6 * n + i for i, f in enumerate(flags) if f])
    fixed = np.asarray(fixed, dtype=int)
    free = np.setdiff1d(np.arange(n_dof), fixed, assume_unique=True)
    return fixed, free


def linear_solve(P_global, K_global, fixed, free):
    n_dof = len(fixed) + len(free)
    K_ff = K_global[np.ix_(free, free)]
    K_sf = K_global[np.ix_(fixed, free)]
    cond = np.linalg.cond(K_ff)
    if cond > 1e16:
        raise ValueError(f"Stiffness matrix is ill-conditioned (cond={cond:.2e})")
    u_f = np.linalg.solve(K_ff, P_global[free])
    u = np.zeros(n_dof)
    u[free] = u_f
    reactions = np.zeros(P_global.shape)
    reactions[fixed] = K_sf @ u_f - P_global[fixed]
    return u, reactions


# ---------------------------------------------------------------------------
#  Force recovery
# ---------------------------------------------------------------------------

def compute_element_forces(ele, xi, yi, zi, xj, yj, zj, u_dofs_global):
    L = np.linalg.norm([xj - xi, yj - yi, zj - zi])
    Gamma = transformation_matrix_3D(
        xi, yi, zi, xj, yj, zj, ele.get('local_z')
    )
    k_local = local_elastic_stiffness_3D(
        ele['E'], ele['nu'], ele['A'], L,
        ele['I_y'], ele['I_z'], ele['J']
    )
    u_local = Gamma @ u_dofs_global
    return k_local @ u_local


# ---------------------------------------------------------------------------
#  Geometric stiffness matrix
# ---------------------------------------------------------------------------

def local_geometric_stiffness_3D(L, A, I_rho, Fx2, Mx2, My1, Mz1, My2, Mz2):
    k_g = np.zeros((12, 12))

    # Upper triangle off-diagonal terms
    k_g[0, 6] = -Fx2 / L
    k_g[1, 3] = My1 / L
    k_g[1, 4] = Mx2 / L
    k_g[1, 5] = Fx2 / 10.0
    k_g[1, 7] = -6.0 * Fx2 / (5.0 * L)
    k_g[1, 9] = My2 / L
    k_g[1, 10] = -Mx2 / L
    k_g[1, 11] = Fx2 / 10.0
    k_g[2, 3] = Mz1 / L
    k_g[2, 4] = -Fx2 / 10.0
    k_g[2, 5] = Mx2 / L
    k_g[2, 8] = -6.0 * Fx2 / (5.0 * L)
    k_g[2, 9] = Mz2 / L
    k_g[2, 10] = -Fx2 / 10.0
    k_g[2, 11] = -Mx2 / L
    k_g[3, 4] = -(2.0 * Mz1 - Mz2) / 6.0
    k_g[3, 5] = (2.0 * My1 - My2) / 6.0
    k_g[3, 7] = -My1 / L
    k_g[3, 8] = -Mz1 / L
    k_g[3, 9] = -Fx2 * I_rho / (A * L)
    k_g[3, 10] = -(Mz1 + Mz2) / 6.0
    k_g[3, 11] = (My1 + My2) / 6.0
    k_g[4, 7] = -Mx2 / L
    k_g[4, 8] = Fx2 / 10.0
    k_g[4, 9] = -(Mz1 + Mz2) / 6.0
    k_g[4, 10] = -Fx2 * L / 30.0
    k_g[4, 11] = Mx2 / 2.0
    k_g[5, 7] = -Fx2 / 10.0
    k_g[5, 8] = -Mx2 / L
    k_g[5, 9] = (My1 + My2) / 6.0
    k_g[5, 10] = -Mx2 / 2.0
    k_g[5, 11] = -Fx2 * L / 30.0
    k_g[7, 9] = -My2 / L
    k_g[7, 10] = Mx2 / L
    k_g[7, 11] = -Fx2 / 10.0
    k_g[8, 9] = -Mz2 / L
    k_g[8, 10] = Fx2 / 10.0
    k_g[8, 11] = Mx2 / L
    k_g[9, 10] = (Mz1 - 2.0 * Mz2) / 6.0
    k_g[9, 11] = -(My1 - 2.0 * My2) / 6.0

    # Symmetrise
    k_g = k_g + k_g.T

    # Diagonal terms
    k_g[0, 0] = Fx2 / L
    k_g[1, 1] = 6.0 * Fx2 / (5.0 * L)
    k_g[2, 2] = 6.0 * Fx2 / (5.0 * L)
    k_g[3, 3] = Fx2 * I_rho / (A * L)
    k_g[4, 4] = 2.0 * Fx2 * L / 15.0
    k_g[5, 5] = 2.0 * Fx2 * L / 15.0
    k_g[6, 6] = Fx2 / L
    k_g[7, 7] = 6.0 * Fx2 / (5.0 * L)
    k_g[8, 8] = 6.0 * Fx2 / (5.0 * L)
    k_g[9, 9] = Fx2 * I_rho / (A * L)
    k_g[10, 10] = 2.0 * Fx2 * L / 15.0
    k_g[11, 11] = 2.0 * Fx2 * L / 15.0

    return k_g


# ---------------------------------------------------------------------------
#  Global geometric stiffness assembly
# ---------------------------------------------------------------------------

def assemble_geometric_stiffness(node_coords, elements, u_global):
    node_coords = np.asarray(node_coords, dtype=float)
    u_global = np.asarray(u_global, dtype=float)
    n_nodes = node_coords.shape[0]
    n_dof = 6 * n_nodes
    K_g = np.zeros((n_dof, n_dof), dtype=float)

    for ele in elements:
        ni = int(ele['node_i'])
        nj = int(ele['node_j'])
        xi, yi, zi = node_coords[ni]
        xj, yj, zj = node_coords[nj]
        L = float(np.linalg.norm([xj - xi, yj - yi, zj - zi]))
        A = float(ele['A'])
        I_rho = float(ele['I_rho'])

        Gamma = transformation_matrix_3D(
            xi, yi, zi, xj, yj, zj, ele.get('local_z')
        )
        dofs = _node_dofs(ni) + _node_dofs(nj)
        u_e_global = u_global[dofs]

        load_local = compute_element_forces(
            ele, xi, yi, zi, xj, yj, zj, u_e_global
        )

        Fx2 = float(load_local[6])
        Mx2 = float(load_local[9])
        My1 = float(load_local[4])
        Mz1 = float(load_local[5])
        My2 = float(load_local[10])
        Mz2 = float(load_local[11])

        k_g_local = local_geometric_stiffness_3D(
            L, A, I_rho, Fx2, Mx2, My1, Mz1, My2, Mz2
        )
        k_g_global = Gamma.T @ k_g_local @ Gamma
        K_g[np.ix_(dofs, dofs)] += k_g_global

    return K_g


# ---------------------------------------------------------------------------
#  Eigenvalue buckling solve
# ---------------------------------------------------------------------------

def eigenvalue_buckling_solve(K_e_global, K_g_global, boundary_conditions, n_nodes):
    c_eps = 1e3 * np.finfo(float).eps

    _, free = partition_dofs(boundary_conditions, n_nodes)
    free = np.asarray(free, dtype=int)

    K_e_ff = K_e_global[np.ix_(free, free)]
    K_g_ff = K_g_global[np.ix_(free, free)]

    K_e_ff = 0.5 * (K_e_ff + K_e_ff.T)
    K_g_ff = 0.5 * (K_g_ff + K_g_ff.T)

    cond_e = np.linalg.cond(K_e_ff)
    if not np.isfinite(cond_e) or cond_e > 1e16:
        raise ValueError(f"Elastic stiffness ill-conditioned (cond={cond_e:.3e})")

    cond_g = np.linalg.cond(K_g_ff)
    if not np.isfinite(cond_g) or cond_g > 1e16:
        raise ValueError(f"Geometric stiffness ill-conditioned (cond={cond_g:.3e})")

    eig_vals, eig_vecs = scipy.linalg.eig(K_e_ff, -1.0 * K_g_ff, check_finite=False)

    if eig_vals.size == 0:
        raise ValueError("Eigenvalue solver returned no eigenvalues.")

    lam_max = float(np.max(np.abs(eig_vals)))
    rel_imag = np.max(np.abs(np.imag(eig_vals))) / max(lam_max, 1.0)

    if rel_imag <= c_eps:
        V = eig_vecs.copy()
        for j in range(V.shape[1]):
            col = V[:, j]
            k_idx = int(np.argmax(np.abs(col)))
            phase = np.conj(col[k_idx]) / (abs(col[k_idx]) + 1e-300)
            V[:, j] = phase * col
        eig_vals = np.real(eig_vals)
        eig_vecs = np.real(V)
    else:
        raise ValueError(f"Complex eigenpairs detected (rel_imag={rel_imag:.3e})")

    vals = eig_vals.astype(float, copy=False)
    finite_mask = np.isfinite(vals)
    lam_scale = np.max(np.abs(vals[finite_mask])) if np.any(finite_mask) else 1.0
    pos_cut = max(1e-12, c_eps * lam_scale)

    candidates = np.flatnonzero(finite_mask & (vals > pos_cut))
    if candidates.size == 0:
        raise ValueError("No positive buckling load factors found.")

    ix = candidates[np.argmin(vals[candidates])]
    critical_load_factor = float(vals[ix])
    mode_free = eig_vecs[:, ix].astype(float, copy=False)

    num_dofs = 6 * n_nodes
    mode = np.zeros(num_dofs, dtype=float)
    mode[free] = mode_free

    return critical_load_factor, mode


# ---------------------------------------------------------------------------
#  Main pipeline
# ---------------------------------------------------------------------------

def elastic_critical_load_analysis(
    node_coords: np.ndarray,
    elements: Sequence[dict],
    boundary_conditions: dict,
    nodal_loads: dict,
):
    n_nodes = node_coords.shape[0]
    K = assemble_elastic_stiffness(node_coords, elements)
    P = assemble_load_vector(nodal_loads, n_nodes)
    fixed, free = partition_dofs(boundary_conditions, n_nodes)
    u_global, _ = linear_solve(P, K, fixed, free)
    K_g = assemble_geometric_stiffness(node_coords, elements, u_global)
    lam, mode = eigenvalue_buckling_solve(K, K_g, boundary_conditions, n_nodes)
    return lam, mode
'''

with open('/app/buckling_analysis.py', 'w') as f:
    f.write(CORRECTED_CODE)
print("Step 3: Wrote corrected buckling_analysis.py")

# ============================================================
# Step 4: Quick verification
# ============================================================
sys.path.insert(0, '/app')
import importlib
ba = importlib.import_module('buckling_analysis')

# Verify geometric stiffness properties
import numpy as np
K = ba.local_geometric_stiffness_3D(2.0, 0.01, 5e-6, 1000.0, 0.0, 0.0, 0.0, 0.0, 0.0)
assert K.shape == (12, 12), f"Wrong shape: {K.shape}"
assert np.allclose(K, K.T), "Not symmetric"

# Verify a simple cantilever
E, nu = 1000.0, 0.3
L, r = 10.0, 0.5
n_nodes = 11
n_elems = 10
z = np.linspace(0.0, L, n_nodes)
node_coords = np.c_[np.zeros_like(z), np.zeros_like(z), z]
A = np.pi * r**2
I = np.pi * r**4 / 4.0
J = np.pi * r**4 / 2.0
elements = [
    dict(node_i=i, node_j=i+1, E=E, nu=nu, A=A,
         I_y=I, I_z=I, J=J, I_rho=J,
         local_z=np.array([1.0, 0.0, 0.0]))
    for i in range(n_elems)
]
bc = {0: [True]*6}
loads = {n: [0.0]*6 for n in range(n_nodes)}
loads[n_nodes-1][2] = -1.0
lam, mode = ba.elastic_critical_load_analysis(node_coords, elements, bc, loads)
Pcr_analytical = np.pi**2 * E * I / (4.0 * L**2)
Pcr_numeric = lam * 1.0
rel_err = abs(Pcr_numeric - Pcr_analytical) / Pcr_analytical
assert rel_err < 1e-5, f"Euler mismatch: rel_err={rel_err:.3e}"
print(f"Step 4: Verification passed (Euler rel_err={rel_err:.2e})")
