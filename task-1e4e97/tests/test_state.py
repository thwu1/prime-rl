
"""
Tests for 3D frame eigenvalue buckling analysis.

Verifies the geometric stiffness matrix implementation and the complete
buckling analysis pipeline against analytical Euler buckling solutions.
"""
import numpy as np
import pytest
import sys

sys.path.insert(0, '/app')

from frame3d import elastic_critical_load
from frame3d.buckling import local_geometric_stiffness_3d


class TestLocalGeometricStiffnessProperties:
    """Verify structural properties of the local geometric stiffness matrix."""

    def test_shape_is_12x12(self):
        K = local_geometric_stiffness_3d(
            2.0, 0.01, 5e-6, 1000.0, 200.0, 50.0, -75.0, -25.0, 100.0
        )
        assert K.shape == (12, 12), f"Expected (12,12), got {K.shape}"

    def test_symmetry(self):
        K = local_geometric_stiffness_3d(
            2.0, 0.01, 5e-6, 1000.0, 200.0, 50.0, -75.0, -25.0, 100.0
        )
        assert np.allclose(K, K.T, atol=1e-10), "Matrix must be symmetric"

    def test_zero_when_all_forces_zero(self):
        K = local_geometric_stiffness_3d(
            2.0, 0.01, 5e-6, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        )
        assert np.allclose(K, 0.0), "Matrix must be zero when all inputs are zero"

    def test_linear_scaling_with_axial_force(self):
        args_base = (2.0, 0.01, 5e-6, 1000.0, 200.0, 50.0, -75.0, -25.0, 100.0)
        args_double = (2.0, 0.01, 5e-6, 2000.0, 200.0, 50.0, -75.0, -25.0, 100.0)
        K1 = local_geometric_stiffness_3d(*args_base)
        K2 = local_geometric_stiffness_3d(*args_double)
        # Diagonal entries proportional to Fx2 should double
        assert np.isclose(K2[0, 0], 2.0 * K1[0, 0], rtol=1e-10)
        assert np.isclose(K2[1, 1], 2.0 * K1[1, 1], rtol=1e-10)
        assert np.isclose(K2[3, 3], 2.0 * K1[3, 3], rtol=1e-10)


class TestLocalGeometricStiffnessValues:
    """Verify specific matrix entries against known formulas."""

    def test_axial_diagonal_entries(self):
        L, A, I_rho = 1.0, 1.0, 1.0
        Fx2 = 1.0
        K = local_geometric_stiffness_3d(L, A, I_rho, Fx2, 0, 0, 0, 0, 0)
        assert np.isclose(K[0, 0], Fx2 / L)
        assert np.isclose(K[1, 1], 6.0 * Fx2 / (5.0 * L))
        assert np.isclose(K[2, 2], 6.0 * Fx2 / (5.0 * L))
        assert np.isclose(K[3, 3], Fx2 * I_rho / (A * L))
        assert np.isclose(K[4, 4], 2.0 * Fx2 * L / 15.0)
        assert np.isclose(K[5, 5], 2.0 * Fx2 * L / 15.0)
        assert np.isclose(K[6, 6], Fx2 / L)
        assert np.isclose(K[7, 7], 6.0 * Fx2 / (5.0 * L))
        assert np.isclose(K[8, 8], 6.0 * Fx2 / (5.0 * L))
        assert np.isclose(K[9, 9], Fx2 * I_rho / (A * L))
        assert np.isclose(K[10, 10], 2.0 * Fx2 * L / 15.0)
        assert np.isclose(K[11, 11], 2.0 * Fx2 * L / 15.0)

    def test_axial_offdiagonal_entries(self):
        L, A, I_rho = 1.0, 1.0, 1.0
        Fx2 = 1.0
        K = local_geometric_stiffness_3d(L, A, I_rho, Fx2, 0, 0, 0, 0, 0)
        assert np.isclose(K[0, 6], -Fx2 / L)
        assert np.isclose(K[1, 5], Fx2 / 10.0)
        assert np.isclose(K[1, 7], -6.0 * Fx2 / (5.0 * L))
        assert np.isclose(K[1, 11], Fx2 / 10.0)
        assert np.isclose(K[2, 4], -Fx2 / 10.0)
        assert np.isclose(K[2, 8], -6.0 * Fx2 / (5.0 * L))
        assert np.isclose(K[2, 10], -Fx2 / 10.0)
        assert np.isclose(K[3, 9], -Fx2 * I_rho / (A * L))
        assert np.isclose(K[4, 10], -Fx2 * L / 30.0)
        assert np.isclose(K[5, 11], -Fx2 * L / 30.0)

    def test_moment_coupling_entries(self):
        L, A, I_rho = 2.0, 0.01, 5e-6
        Fx2, Mx2 = 1000.0, 200.0
        My1, Mz1, My2, Mz2 = 50.0, -75.0, -25.0, 100.0
        K = local_geometric_stiffness_3d(
            L, A, I_rho, Fx2, Mx2, My1, Mz1, My2, Mz2
        )
        # Moment-displacement coupling
        assert np.isclose(K[1, 3], My1 / L, rtol=1e-10)
        assert np.isclose(K[1, 4], Mx2 / L, rtol=1e-10)
        assert np.isclose(K[2, 3], Mz1 / L, rtol=1e-10)
        assert np.isclose(K[2, 5], Mx2 / L, rtol=1e-10)
        assert np.isclose(K[1, 9], My2 / L, rtol=1e-10)
        assert np.isclose(K[1, 10], -Mx2 / L, rtol=1e-10)
        assert np.isclose(K[2, 9], Mz2 / L, rtol=1e-10)
        assert np.isclose(K[2, 11], -Mx2 / L, rtol=1e-10)
        # Torsion-bending coupling
        assert np.isclose(K[4, 11], Mx2 / 2.0, rtol=1e-10)
        assert np.isclose(K[5, 10], -Mx2 / 2.0, rtol=1e-10)
        # Polar inertia coupling
        assert np.isclose(K[3, 9], -Fx2 * I_rho / (A * L), rtol=1e-10)

    def test_compression_softens_stiffness(self):
        L, A, I_rho = 2.0, 0.01, 5e-6
        Mx2, My1, Mz1, My2, Mz2 = 200.0, 50.0, -75.0, -25.0, 100.0
        K_tens = local_geometric_stiffness_3d(
            L, A, I_rho, 1000.0, Mx2, My1, Mz1, My2, Mz2
        )
        K_comp = local_geometric_stiffness_3d(
            L, A, I_rho, -1000.0, Mx2, My1, Mz1, My2, Mz2
        )
        assert K_tens[1, 1] > K_comp[1, 1]
        assert K_tens[3, 3] > K_comp[3, 3]


class TestEulerBucklingCantilever:
    """Verify against analytical Euler buckling for cantilever columns."""

    def test_parameter_sweep(self):
        """Sweep radii and lengths; compare with analytical Euler loads."""
        E = 1000.0
        nu = 0.3
        num_nodes = 11
        n_elems = num_nodes - 1
        P_ref = 1.0

        for L in [10.0, 20.0, 40.0]:
            for r in [0.5, 0.75, 1.0]:
                z = np.linspace(0.0, L, num_nodes)
                node_coords = np.c_[
                    np.zeros_like(z), np.zeros_like(z), z
                ]

                A = np.pi * r ** 2
                I_y = np.pi * r ** 4 / 4.0
                I_z = I_y
                I_rho = np.pi * r ** 4 / 2.0
                J = I_rho

                elements = [
                    dict(
                        node_i=i, node_j=i + 1, E=E, nu=nu, A=A,
                        I_y=I_y, I_z=I_z, J=J, I_rho=I_rho,
                        local_z=np.array([1.0, 0.0, 0.0]),
                    )
                    for i in range(n_elems)
                ]

                boundary_conditions = {0: [True] * 6}
                nodal_loads = {
                    n: [0.0] * 6 for n in range(num_nodes)
                }
                nodal_loads[num_nodes - 1][2] = -P_ref

                lam, mode = elastic_critical_load(
                    node_coords, elements,
                    boundary_conditions, nodal_loads,
                )

                assert np.isfinite(lam) and lam > 0.0
                assert mode.shape == (6 * num_nodes,)
                assert np.all(np.isfinite(mode))

                Pcr_analytical = (np.pi ** 2) * E * I_z / (4.0 * L ** 2)
                Pcr_numeric = lam * P_ref
                rel_err = abs(Pcr_numeric - Pcr_analytical) / Pcr_analytical

                assert rel_err < 1e-5, (
                    f"Euler mismatch for L={L}, r={r}: "
                    f"rel_err={rel_err:.3e} "
                    f"(numeric={Pcr_numeric:.6e}, "
                    f"analytical={Pcr_analytical:.6e})"
                )

    def test_mesh_convergence(self):
        """Error must decrease monotonically with mesh refinement."""
        E, nu = 1000.0, 0.30
        L = 20.0
        r = 1.0
        P_ref = 1.0

        A = np.pi * r ** 2
        I_y = np.pi * r ** 4 / 4.0
        I_z = I_y
        I_rho = np.pi * r ** 4 / 2.0
        J = I_rho

        Pcr_exact = (np.pi ** 2) * E * I_z / (4.0 * L ** 2)

        meshes = [10, 20, 30, 40]
        rel_errors = []

        for n_elems in meshes:
            n_nodes = n_elems + 1
            z = np.linspace(0.0, L, n_nodes)
            node_coords = np.c_[
                np.zeros_like(z), np.zeros_like(z), z
            ]

            elements = [
                dict(
                    node_i=i, node_j=i + 1, E=E, nu=nu, A=A,
                    I_y=I_y, I_z=I_z, J=J, I_rho=I_rho,
                    local_z=np.array([1.0, 0.0, 0.0]),
                )
                for i in range(n_elems)
            ]

            boundary_conditions = {0: [True] * 6}
            nodal_loads = {n: [0.0] * 6 for n in range(n_nodes)}
            nodal_loads[n_nodes - 1][2] = -P_ref

            lam, mode = elastic_critical_load(
                node_coords, elements,
                boundary_conditions, nodal_loads,
            )

            assert np.isfinite(lam) and lam > 0.0
            Pcr_num = lam * P_ref
            rel_err = abs(Pcr_num - Pcr_exact) / Pcr_exact
            rel_errors.append(rel_err)

        # Monotone improvement (allow tiny numerical wiggle)
        for i in range(1, len(rel_errors)):
            assert rel_errors[i] <= rel_errors[i - 1] * 1.02 + 1e-12, (
                f"Error did not decrease at step {i}: "
                f"{rel_errors[i-1]:.3e} -> {rel_errors[i]:.3e}"
            )

        # Finest mesh should be very accurate
        assert rel_errors[-1] < 1e-6, (
            f"Finest mesh error too large: {rel_errors[-1]:.3e}"
        )

    def test_orientation_invariance(self):
        """Critical load factor must be invariant under rigid rotation."""
        E, nu = 1000.0, 0.30
        L = 2.0
        num_nodes = 11
        n_elems = num_nodes - 1

        b, h = 0.08, 0.05
        A = b * h
        Iy = b * h ** 3 / 12.0
        Iz = h * b ** 3 / 12.0
        if b < h:
            b, h = h, b
        J = b * h ** 3 * (
            1.0 / 3.0 - 0.21 * (h / b) * (1 - h ** 4 / (12 * b ** 4))
        )
        I_rho = Iy + Iz

        # Base model along +z
        z = np.linspace(0.0, L, num_nodes)
        node_coords = np.c_[
            np.zeros_like(z), np.zeros_like(z), z
        ]

        elements = [
            dict(
                node_i=i, node_j=i + 1, E=E, nu=nu, A=A,
                I_y=Iy, I_z=Iz, J=J, I_rho=I_rho,
                local_z=np.array([0.0, 1.0, 0.0]),
            )
            for i in range(n_elems)
        ]

        boundary_conditions = {0: [True] * 6}
        P_ref = 1.0
        nodal_loads = {n: [0.0] * 6 for n in range(num_nodes)}
        nodal_loads[num_nodes - 1][2] = -P_ref

        lam_base, _ = elastic_critical_load(
            node_coords, elements,
            boundary_conditions, nodal_loads,
        )

        # Rigid rotation: 35 deg about [2, -1, 0.5]
        a = np.array([2.0, -1.0, 0.5])
        a /= np.linalg.norm(a)
        ax, ay, az = a
        theta = np.deg2rad(35.0)
        c = np.cos(theta)
        s = np.sin(theta)
        C = 1.0 - c
        R = np.array([
            [c + ax * ax * C, ax * ay * C - az * s, ax * az * C + ay * s],
            [ay * ax * C + az * s, c + ay * ay * C, ay * az * C - ax * s],
            [az * ax * C - ay * s, az * ay * C + ax * s, c + az * az * C],
        ])

        node_coords_rot = (R @ node_coords.T).T

        elements_rot = []
        for e in elements:
            e_rot = dict(e)
            e_rot["local_z"] = R @ e["local_z"]
            elements_rot.append(e_rot)

        F_tip = np.array([0.0, 0.0, -P_ref])
        F_tip_rot = R @ F_tip
        nodal_loads_rot = {n: [0.0] * 6 for n in range(num_nodes)}
        nodal_loads_rot[num_nodes - 1][0] = float(F_tip_rot[0])
        nodal_loads_rot[num_nodes - 1][1] = float(F_tip_rot[1])
        nodal_loads_rot[num_nodes - 1][2] = float(F_tip_rot[2])

        lam_rot, _ = elastic_critical_load(
            node_coords_rot, elements_rot,
            {0: [True] * 6}, nodal_loads_rot,
        )

        assert np.isfinite(lam_base) and lam_base > 0
        assert np.isfinite(lam_rot) and lam_rot > 0
        assert np.isclose(lam_rot, lam_base, rtol=1e-9), (
            f"lambda not invariant: base={lam_base:.6e}, rot={lam_rot:.6e}"
        )
