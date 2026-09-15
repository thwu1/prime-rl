
"""
Tests for 3D frame eigenvalue buckling analysis pipeline.

Verifies:
  1. Geometric stiffness matrix component-level properties
  2. Accuracy against analytical Euler buckling solutions
  3. Orientation invariance under rigid rotation
  4. Mesh convergence behavior
"""

import sys
sys.path.insert(0, '/app')

import numpy as np
import pytest
from buckling_analysis import elastic_critical_load_analysis, local_geometric_stiffness_3D


def test_geometric_stiffness_properties():
    """
    Verify fundamental properties of the local geometric stiffness matrix:
    shape, symmetry, zero-force behavior, scaling, and coupling effects.
    """
    L = 2.0
    A = 0.01
    I_rho = 5e-6

    Fx2_tens = 1000.0
    Mx2 = 200.0
    My1, Mz1 = 50.0, -75.0
    My2, Mz2 = -25.0, 100.0

    K = local_geometric_stiffness_3D(L, A, I_rho, Fx2_tens, Mx2, My1, Mz1, My2, Mz2)

    # Shape and symmetry
    assert K.shape == (12, 12), "Matrix shape must be 12x12"
    assert np.allclose(K, K.T, atol=1e-10), "Matrix must be symmetric"

    # Zero matrix when all forces are zero
    K_zero = local_geometric_stiffness_3D(L, A, I_rho, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    assert np.allclose(K_zero, 0.0), "Expected zero matrix when all forces are zero"

    # Diagonal P-delta terms scale linearly with Fx2
    K2 = local_geometric_stiffness_3D(L, A, I_rho, 2 * Fx2_tens, Mx2, My1, Mz1, My2, Mz2)
    assert np.isclose(K2[0, 0], 2 * K[0, 0], rtol=1e-10), "k[0,0] should scale with Fx2"
    assert np.isclose(K2[1, 1], 2 * K[1, 1], rtol=1e-10), "k[1,1] should scale with Fx2"
    assert np.isclose(K2[3, 3], 2 * K[3, 3], rtol=1e-10), "k[3,3] should scale with Fx2"

    # Compression softens transverse and torsional stiffness
    Fx2_comp = -1000.0
    K_comp = local_geometric_stiffness_3D(L, A, I_rho, Fx2_comp, Mx2, My1, Mz1, My2, Mz2)
    assert K[1, 1] > K_comp[1, 1], "Transverse stiffness should reduce under compression"
    assert K[3, 3] > K_comp[3, 3], "Torsional stiffness should reduce under compression"

    # Torsion-bending coupling: Mx2 must affect rotation cross-terms
    K_no_mx = local_geometric_stiffness_3D(L, A, I_rho, Fx2_tens, 0.0, My1, Mz1, My2, Mz2)
    assert not np.isclose(K[4, 11], K_no_mx[4, 11], atol=1e-10), "Mx2 should affect k[4,11]"

    # Moment coupling: My1, Mz1, My2, Mz2 must affect torsion-related terms
    K_no_my1 = local_geometric_stiffness_3D(L, A, I_rho, Fx2_tens, Mx2, 0.0, Mz1, My2, Mz2)
    assert not np.isclose(K[1, 3], K_no_my1[1, 3], atol=1e-10), "My1 should affect k[1,3]"

    K_no_mz1 = local_geometric_stiffness_3D(L, A, I_rho, Fx2_tens, Mx2, My1, 0.0, My2, Mz2)
    assert not np.isclose(K[2, 3], K_no_mz1[2, 3], atol=1e-10), "Mz1 should affect k[2,3]"

    K_no_my2 = local_geometric_stiffness_3D(L, A, I_rho, Fx2_tens, Mx2, My1, Mz1, 0.0, Mz2)
    assert not np.isclose(K[1, 9], K_no_my2[1, 9], atol=1e-10), "My2 should affect k[1,9]"

    K_no_mz2 = local_geometric_stiffness_3D(L, A, I_rho, Fx2_tens, Mx2, My1, Mz1, My2, 0.0)
    assert not np.isclose(K[2, 9], K_no_mz2[2, 9], atol=1e-10), "Mz2 should affect k[2,9]"


def test_euler_buckling_cantilever():
    """
    Cantilever (fixed-free) circular column aligned with +z.
    Sweep through radii r in {0.5, 0.75, 1.0} and lengths L in {10, 20, 40}.
    Compare numerical critical load against analytical Euler cantilever formula:
        P_cr = pi^2 * E * I / (4 * L^2)
    Use 10 elements per column, tolerance 1e-5.
    """
    E = 1000.0
    nu = 0.3
    num_nodes = 11
    n_elems = num_nodes - 1
    P_ref = 1.0

    lengths = [10.0, 20.0, 40.0]
    radii = [0.5, 0.75, 1.0]

    for L in lengths:
        for r in radii:
            z = np.linspace(0.0, L, num_nodes)
            node_coords = np.c_[np.zeros_like(z), np.zeros_like(z), z]

            A = np.pi * r**2
            I_y = np.pi * r**4 / 4.0
            I_z = np.pi * r**4 / 4.0
            I_rho = np.pi * r**4 / 2.0
            J = np.pi * r**4 / 2.0

            elements = [
                dict(
                    node_i=i, node_j=i + 1,
                    E=E, nu=nu, A=A, I_y=I_y, I_z=I_z, J=J, I_rho=I_rho,
                    local_z=np.array([1.0, 0.0, 0.0], dtype=float),
                )
                for i in range(n_elems)
            ]

            boundary_conditions = {0: [True, True, True, True, True, True]}

            nodal_loads = {n: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
                          for n in range(num_nodes)}
            nodal_loads[num_nodes - 1][2] = -P_ref

            lam, mode = elastic_critical_load_analysis(
                node_coords=node_coords,
                elements=elements,
                boundary_conditions=boundary_conditions,
                nodal_loads=nodal_loads,
            )

            assert np.isfinite(lam) and lam > 0.0
            assert mode.shape == (6 * num_nodes,)
            assert np.all(np.isfinite(mode))

            I = I_z
            Pcr_analytical = (np.pi**2) * E * I / (4.0 * L**2)
            Pcr_numeric = lam * P_ref
            rel_err = abs(Pcr_numeric - Pcr_analytical) / Pcr_analytical

            assert rel_err < 1e-5, (
                f"Euler mismatch for L={L}, r={r}: "
                f"rel_err={rel_err:.3e} "
                f"(P_num={Pcr_numeric:.6e}, P_anal={Pcr_analytical:.6e})"
            )


def test_orientation_invariance():
    """
    Verify that the critical load factor is invariant under rigid rotation.

    A cantilever with rectangular cross-section (Iy != Iz) is solved in its
    base orientation and again after rotating the geometry, element axes,
    and applied load by 35 degrees about an arbitrary axis. The critical load
    factor must be identical and the mode shape must transform consistently.
    """
    E, nu = 1000.0, 0.30
    L = 2.0
    num_nodes = 11
    n_elems = num_nodes - 1

    z = np.linspace(0.0, L, num_nodes)
    node_coords = np.c_[np.zeros_like(z), np.zeros_like(z), z]

    b, h = 0.08, 0.05
    A = b * h
    Iy = b * h**3 / 12.0
    Iz = h * b**3 / 12.0
    if b < h:
        b, h = h, b
    J = b * h**3 * (1.0 / 3.0 - 0.21 * (h / b) * (1.0 - (h**4) / (12.0 * b**4)))
    I_rho = Iy + Iz

    elements = [
        dict(
            node_i=i, node_j=i + 1,
            E=E, nu=nu, A=A, I_y=Iy, I_z=Iz, J=J, I_rho=I_rho,
            local_z=np.array([0.0, 1.0, 0.0], dtype=float),
        )
        for i in range(n_elems)
    ]

    boundary_conditions = {0: [True, True, True, True, True, True]}
    P_ref = 1.0
    nodal_loads = {n: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0] for n in range(num_nodes)}
    nodal_loads[num_nodes - 1][2] = -P_ref

    lam_base, mode_base = elastic_critical_load_analysis(
        node_coords=node_coords,
        elements=elements,
        boundary_conditions=boundary_conditions,
        nodal_loads=nodal_loads,
    )

    # Rotation matrix: 35 degrees about axis [2, -1, 0.5]
    a = np.array([2.0, -1.0, 0.5], dtype=float)
    a /= np.linalg.norm(a)
    x, y, zax = a
    theta = np.deg2rad(35.0)
    c, s, C = np.cos(theta), np.sin(theta), 1.0 - np.cos(theta)
    R = np.array([
        [c + x * x * C,       x * y * C - zax * s, x * zax * C + y * s],
        [y * x * C + zax * s, c + y * y * C,       y * zax * C - x * s],
        [zax * x * C - y * s, zax * y * C + x * s, c + zax * zax * C],
    ], dtype=float)

    node_coords_rot = (R @ node_coords.T).T

    elements_rot = []
    for e in elements:
        e_rot = dict(e)
        e_rot['local_z'] = R @ e['local_z']
        elements_rot.append(e_rot)

    F_tip_base = np.array([0.0, 0.0, -P_ref], dtype=float)
    F_tip_rot = R @ F_tip_base
    nodal_loads_rot = {n: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
                       for n in range(num_nodes)}
    nodal_loads_rot[num_nodes - 1][0] = F_tip_rot[0]
    nodal_loads_rot[num_nodes - 1][1] = F_tip_rot[1]
    nodal_loads_rot[num_nodes - 1][2] = F_tip_rot[2]

    boundary_conditions_rot = {0: [True, True, True, True, True, True]}

    lam_rot, mode_rot = elastic_critical_load_analysis(
        node_coords=node_coords_rot,
        elements=elements_rot,
        boundary_conditions=boundary_conditions_rot,
        nodal_loads=nodal_loads_rot,
    )

    # Check critical load factor invariance
    assert np.isfinite(lam_base) and lam_base > 0
    assert np.isfinite(lam_rot) and lam_rot > 0
    assert np.isclose(lam_rot, lam_base, rtol=1e-9, atol=0.0), (
        f"Critical load not invariant: base={lam_base:.6e}, rot={lam_rot:.6e}"
    )

    # Check mode shape transforms correctly: mode_rot ~ T @ mode_base
    ndof = 6 * num_nodes
    T = np.zeros((ndof, ndof), dtype=float)
    for n in range(num_nodes):
        bidx = 6 * n
        T[bidx:bidx + 3, bidx:bidx + 3] = R
        T[bidx + 3:bidx + 6, bidx + 3:bidx + 6] = R

    mode_expected = T @ mode_base

    # Compare on free DOFs only (node 0 clamped: DOFs 0..5 fixed)
    free = np.arange(6, ndof, dtype=int)
    v1, v2 = mode_rot[free], mode_expected[free]
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    assert n1 > 0 and n2 > 0, "Degenerate mode encountered."

    v1n, v2n = v1 / n1, v2 / n2
    err = min(np.linalg.norm(v1n - v2n), np.linalg.norm(v1n + v2n))
    assert err < 1e-5, f"Rotated mode does not match T @ base mode (err={err:.3e})"


def test_mesh_convergence():
    """
    Verify mesh convergence for Euler buckling of a fixed-free circular cantilever.
    Refine the discretization and check that the numerical critical load approaches
    the analytical Euler value with decreasing relative error.
    """
    E, nu = 1000.0, 0.30
    L = 20.0
    r = 1.0
    P_ref = 1.0

    A = np.pi * r**2
    I_y = np.pi * r**4 / 4.0
    I_z = np.pi * r**4 / 4.0
    I_rho = np.pi * r**4 / 2.0
    J = np.pi * r**4 / 2.0

    Pcr_exact = (np.pi**2) * E * I_z / (4.0 * L**2)

    meshes = [10, 20, 30, 40]
    rel_errors = []

    for n_elems in meshes:
        n_nodes = n_elems + 1
        z = np.linspace(0.0, L, n_nodes)
        node_coords = np.c_[np.zeros_like(z), np.zeros_like(z), z]

        elements = [
            dict(
                node_i=i, node_j=i + 1,
                E=E, nu=nu, A=A, I_y=I_y, I_z=I_z, J=J, I_rho=I_rho,
                local_z=np.array([1.0, 0.0, 0.0], dtype=float),
            )
            for i in range(n_elems)
        ]

        boundary_conditions = {0: [True, True, True, True, True, True]}
        nodal_loads = {n: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
                       for n in range(n_nodes)}
        nodal_loads[n_nodes - 1][2] = -P_ref

        lam, mode = elastic_critical_load_analysis(
            node_coords=node_coords,
            elements=elements,
            boundary_conditions=boundary_conditions,
            nodal_loads=nodal_loads,
        )

        assert np.isfinite(lam) and lam > 0.0
        assert mode.shape == (6 * n_nodes,)
        assert np.all(np.isfinite(mode))

        Pcr_num = lam * P_ref
        rel_err = abs(Pcr_num - Pcr_exact) / Pcr_exact
        rel_errors.append(rel_err)

    # Monotone improvement
    for i in range(1, len(rel_errors)):
        assert rel_errors[i] <= rel_errors[i - 1] * 1.02 + 1e-12, (
            f"Error did not decrease: {rel_errors[i-1]:.3e} -> {rel_errors[i]:.3e} "
            f"for meshes {meshes[i-1]}->{meshes[i]}"
        )

    # Finest mesh must be very accurate
    assert rel_errors[-1] < 1e-6, (
        f"Finest mesh error too large: {rel_errors[-1]:.3e} "
        f"(meshes={meshes}, errors={[f'{e:.3e}' for e in rel_errors]})"
    )
