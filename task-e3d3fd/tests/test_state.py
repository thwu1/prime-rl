
import sys
sys.path.insert(0, '/app')

import numpy as np
import pytest
from fem_buckling import elastic_critical_load_analysis


class TestEulerBucklingCantilever:
    """
    Cantilever (fixed-free) circular column along +z.
    Sweep through radii and lengths, compare lambda*P_ref against the
    analytical Euler cantilever buckling load: P_cr = pi^2 * E * I / (4 * L^2).
    Uses 10 elements; expects relative error below 1e-5.
    """

    E = 2.1e5
    NU = 0.3
    NUM_NODES = 11
    N_ELEMS = 10
    P_REF = 1.0
    LENGTHS = [5.0, 10.0, 15.0]
    RADII = [0.1, 0.15, 0.2]

    @pytest.mark.parametrize("L", LENGTHS)
    @pytest.mark.parametrize("r", RADII)
    def test_euler_buckling(self, L, r):
        z = np.linspace(0.0, L, self.NUM_NODES)
        node_coords = np.column_stack(
            [np.zeros_like(z), np.zeros_like(z), z]
        )

        A = np.pi * r ** 2
        I_y = np.pi * r ** 4 / 4.0
        I_z = np.pi * r ** 4 / 4.0
        I_rho = np.pi * r ** 4 / 2.0
        J = np.pi * r ** 4 / 2.0

        elements = [
            dict(
                node_i=i, node_j=i + 1,
                E=self.E, nu=self.NU, A=A,
                I_y=I_y, I_z=I_z, J=J, I_rho=I_rho,
                local_z=np.array([1.0, 0.0, 0.0]),
            )
            for i in range(self.N_ELEMS)
        ]

        boundary_conditions = {0: [1, 1, 1, 1, 1, 1]}

        nodal_loads = {n: [0.0] * 6 for n in range(self.NUM_NODES)}
        nodal_loads[self.NUM_NODES - 1][2] = -self.P_REF

        lam, mode = elastic_critical_load_analysis(
            node_coords, elements, boundary_conditions, nodal_loads
        )

        assert np.isfinite(lam) and lam > 0.0, (
            f"Non-positive/non-finite lambda: {lam}"
        )
        assert mode.shape == (6 * self.NUM_NODES,)
        assert np.all(np.isfinite(mode))

        # Constrained DOFs (node 0) must be zero
        assert np.allclose(mode[:6], 0.0, atol=1e-15), (
            "Mode shape has non-zero values at constrained DOFs"
        )

        Pcr_analytical = (np.pi ** 2) * self.E * I_z / (4.0 * L ** 2)
        Pcr_numeric = lam * self.P_REF
        rel_err = abs(Pcr_numeric - Pcr_analytical) / Pcr_analytical

        assert rel_err < 1e-5, (
            f"Euler mismatch L={L}, r={r}: rel_err={rel_err:.3e} "
            f"(numeric={Pcr_numeric:.6e}, analytic={Pcr_analytical:.6e})"
        )


class TestOrientationInvariance:
    """
    Solve a cantilever with rectangular cross-section (I_y != I_z) in its
    original orientation and again after a 42-degree rigid-body rotation
    about an arbitrary axis. The critical load factor must be identical.
    The mode shape must transform by the rotation matrix.
    """

    def test_invariance(self):
        E, nu = 2.1e5, 0.3
        L = 3.0
        num_nodes = 11
        n_elems = num_nodes - 1

        # Rectangular section
        b, h = 0.10, 0.06
        A = b * h
        Iy = b * h ** 3 / 12.0
        Iz = h * b ** 3 / 12.0
        bm, hm = max(b, h), min(b, h)
        J = bm * hm ** 3 * (
            1.0 / 3.0
            - 0.21 * (hm / bm) * (1.0 - hm ** 4 / (12.0 * bm ** 4))
        )
        I_rho = Iy + Iz

        z = np.linspace(0.0, L, num_nodes)
        node_coords = np.column_stack(
            [np.zeros_like(z), np.zeros_like(z), z]
        )

        elements = [
            dict(
                node_i=i, node_j=i + 1,
                E=E, nu=nu, A=A,
                I_y=Iy, I_z=Iz, J=J, I_rho=I_rho,
                local_z=np.array([0.0, 1.0, 0.0]),
            )
            for i in range(n_elems)
        ]

        boundary_conditions = {0: [1, 1, 1, 1, 1, 1]}
        P_ref = 1.0
        nodal_loads = {n: [0.0] * 6 for n in range(num_nodes)}
        nodal_loads[num_nodes - 1][2] = -P_ref

        lam_base, mode_base = elastic_critical_load_analysis(
            node_coords, elements, boundary_conditions, nodal_loads
        )

        # Rigid rotation: 42 deg about axis [1, -2, 0.5]
        a = np.array([1.0, -2.0, 0.5])
        a /= np.linalg.norm(a)
        theta = np.deg2rad(42.0)
        x, y, zax = a
        c = np.cos(theta)
        s = np.sin(theta)
        C = 1.0 - c
        R = np.array([
            [c + x * x * C, x * y * C - zax * s, x * zax * C + y * s],
            [y * x * C + zax * s, c + y * y * C, y * zax * C - x * s],
            [zax * x * C - y * s, zax * y * C + x * s, c + zax * zax * C],
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
        nodal_loads_rot[num_nodes - 1][0] = F_tip_rot[0]
        nodal_loads_rot[num_nodes - 1][1] = F_tip_rot[1]
        nodal_loads_rot[num_nodes - 1][2] = F_tip_rot[2]

        boundary_conditions_rot = {0: [1, 1, 1, 1, 1, 1]}

        lam_rot, mode_rot = elastic_critical_load_analysis(
            node_coords_rot, elements_rot,
            boundary_conditions_rot, nodal_loads_rot
        )

        # Lambda must be invariant
        assert np.isfinite(lam_base) and lam_base > 0
        assert np.isfinite(lam_rot) and lam_rot > 0
        assert np.isclose(lam_rot, lam_base, rtol=1e-9), (
            f"Lambda not invariant: base={lam_base:.6e}, rot={lam_rot:.6e}"
        )

        # Mode shape must transform: mode_rot ≈ T @ mode_base
        ndof = 6 * num_nodes
        T = np.zeros((ndof, ndof))
        for n in range(num_nodes):
            bidx = 6 * n
            T[bidx : bidx + 3, bidx : bidx + 3] = R
            T[bidx + 3 : bidx + 6, bidx + 3 : bidx + 6] = R

        mode_expected = T @ mode_base
        free = np.arange(6, ndof)
        v1, v2 = mode_rot[free], mode_expected[free]
        n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
        assert n1 > 0 and n2 > 0, "Degenerate mode encountered"
        v1n, v2n = v1 / n1, v2 / n2
        err = min(np.linalg.norm(v1n - v2n), np.linalg.norm(v1n + v2n))
        assert err < 1e-5, (
            f"Rotated mode does not match T @ base mode (err={err:.3e})"
        )


class TestMeshConvergence:
    """
    Refine the mesh for a cantilever and verify that the numerical critical
    load converges monotonically to the analytical Euler value.
    """

    def test_convergence(self):
        E, nu = 2.1e5, 0.3
        L = 10.0
        r = 0.15
        P_ref = 1.0

        A = np.pi * r ** 2
        I_y = np.pi * r ** 4 / 4.0
        I_z = np.pi * r ** 4 / 4.0
        I_rho = np.pi * r ** 4 / 2.0
        J = np.pi * r ** 4 / 2.0

        Pcr_exact = (np.pi ** 2) * E * I_z / (4.0 * L ** 2)

        meshes = [5, 10, 20, 40]
        rel_errors = []

        for n_elems in meshes:
            n_nodes = n_elems + 1
            z = np.linspace(0.0, L, n_nodes)
            node_coords = np.column_stack(
                [np.zeros_like(z), np.zeros_like(z), z]
            )

            elements = [
                dict(
                    node_i=i, node_j=i + 1,
                    E=E, nu=nu, A=A,
                    I_y=I_y, I_z=I_z, J=J, I_rho=I_rho,
                    local_z=np.array([1.0, 0.0, 0.0]),
                )
                for i in range(n_elems)
            ]

            boundary_conditions = {0: [1, 1, 1, 1, 1, 1]}
            nodal_loads = {n: [0.0] * 6 for n in range(n_nodes)}
            nodal_loads[n_nodes - 1][2] = -P_ref

            lam, mode = elastic_critical_load_analysis(
                node_coords, elements, boundary_conditions, nodal_loads
            )

            assert np.isfinite(lam) and lam > 0.0
            assert mode.shape == (6 * n_nodes,)

            Pcr_num = lam * P_ref
            rel_err = abs(Pcr_num - Pcr_exact) / Pcr_exact
            rel_errors.append(rel_err)

        # Monotone improvement (with small numerical wiggle room)
        for i in range(1, len(rel_errors)):
            assert rel_errors[i] <= rel_errors[i - 1] * 1.02 + 1e-12, (
                f"Error did not decrease at step {i}: "
                f"{rel_errors[i - 1]:.3e} -> {rel_errors[i]:.3e} "
                f"(meshes {meshes[i - 1]} -> {meshes[i]})"
            )

        # Finest mesh must be very accurate
        assert rel_errors[-1] < 1e-6, (
            f"Finest mesh error too large: {rel_errors[-1]:.3e}"
        )


class TestMomentCouplingEffect:
    """
    Verify that the geometric stiffness includes moment coupling terms,
    not just axial-force terms. Under combined axial + transverse loading,
    the bending moments affect the geometric stiffness and change the
    critical load factor compared to pure axial loading. An axial-only
    geometric stiffness would give identical results for both load cases
    since the axial force is unchanged by a transverse load on a cantilever.
    """

    def test_moment_terms_affect_eigenvalue(self):
        E, nu = 2.1e5, 0.3
        L = 6.0
        n_elems = 6
        n_nodes = n_elems + 1

        # Rectangular section so I_y != I_z
        b, h = 0.12, 0.06
        A = b * h
        Iy = b * h ** 3 / 12.0
        Iz = h * b ** 3 / 12.0
        bm, hm = max(b, h), min(b, h)
        J = bm * hm ** 3 * (
            1.0 / 3.0
            - 0.21 * (hm / bm) * (1.0 - hm ** 4 / (12.0 * bm ** 4))
        )
        I_rho = Iy + Iz

        z = np.linspace(0.0, L, n_nodes)
        node_coords = np.column_stack(
            [np.zeros_like(z), np.zeros_like(z), z]
        )

        elements = [
            dict(
                node_i=i, node_j=i + 1,
                E=E, nu=nu, A=A,
                I_y=Iy, I_z=Iz, J=J, I_rho=I_rho,
                local_z=np.array([0.0, 1.0, 0.0]),
            )
            for i in range(n_elems)
        ]

        boundary_conditions = {0: [1, 1, 1, 1, 1, 1]}
        P_axial = 1.0

        # Case A: pure axial compression
        loads_A = {n: [0.0] * 6 for n in range(n_nodes)}
        loads_A[n_nodes - 1][2] = -P_axial

        lam_A, _ = elastic_critical_load_analysis(
            node_coords, elements, boundary_conditions, loads_A
        )

        # Case B: axial compression + significant transverse load
        Q_transverse = 0.3
        loads_B = {n: [0.0] * 6 for n in range(n_nodes)}
        loads_B[n_nodes - 1][2] = -P_axial
        loads_B[n_nodes - 1][0] = Q_transverse

        lam_B, _ = elastic_critical_load_analysis(
            node_coords, elements, boundary_conditions, loads_B
        )

        assert np.isfinite(lam_A) and lam_A > 0
        assert np.isfinite(lam_B) and lam_B > 0

        # Lambda MUST differ between the two load cases.
        # If the geometric stiffness only includes axial-force terms, the
        # K_g matrix is identical for both cases (same axial force), giving
        # the same eigenvalue. With moment coupling terms, the transverse
        # load induces bending moments that change K_g and thus lambda.
        rel_diff = abs(lam_A - lam_B) / lam_A
        assert rel_diff > 1e-6, (
            f"Lambda values indistinguishable: pure_axial={lam_A:.6e}, "
            f"combined={lam_B:.6e}, rel_diff={rel_diff:.3e}. "
            "Geometric stiffness likely missing moment coupling terms."
        )
