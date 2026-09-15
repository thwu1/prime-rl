
"""
Tests for 3D beam frame eigenvalue buckling analysis.
Verifies elastic_critical_load_analysis against analytical Euler buckling
solutions, orientation invariance, mesh convergence, TOML model processing,
and cross-validation with an independent Octave implementation.
"""

import json
import os
import subprocess
import numpy as np
import pytest
import sys

sys.path.insert(0, "/app")
from frame3d import elastic_critical_load_analysis


class TestEulerBucklingParameterSweep:
    """
    Cantilever (fixed-free) circular column aligned with +z.
    Sweep radii and lengths, compare lambda*P_ref to the analytical
    Euler cantilever value P_cr = pi^2 * E * I / (4 * L^2).
    """

    @pytest.mark.parametrize(
        "L,r",
        [
            (10.0, 0.5),
            (10.0, 0.75),
            (10.0, 1.0),
            (20.0, 0.5),
            (20.0, 0.75),
            (20.0, 1.0),
            (40.0, 0.5),
            (40.0, 0.75),
            (40.0, 1.0),
        ],
    )
    def test_euler_cantilever(self, L, r):
        E = 1000.0
        nu = 0.3
        num_nodes = 11
        n_elems = num_nodes - 1
        P_ref = 1.0

        z = np.linspace(0.0, L, num_nodes)
        node_coords = np.c_[np.zeros_like(z), np.zeros_like(z), z]

        A = np.pi * r ** 2
        I_y = np.pi * r ** 4 / 4.0
        I_z = np.pi * r ** 4 / 4.0
        I_rho = np.pi * r ** 4 / 2.0
        J = np.pi * r ** 4 / 2.0

        elements = [
            dict(
                node_i=i,
                node_j=i + 1,
                E=E,
                nu=nu,
                A=A,
                I_y=I_y,
                I_z=I_z,
                J=J,
                I_rho=I_rho,
                local_z=np.array([1.0, 0.0, 0.0], dtype=float),
            )
            for i in range(n_elems)
        ]

        boundary_conditions = {0: [True, True, True, True, True, True]}

        nodal_loads = {n: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0] for n in range(num_nodes)}
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
        Pcr_analytical = (np.pi ** 2) * E * I / (4.0 * L ** 2)
        Pcr_numeric = lam * P_ref
        rel_err = abs(Pcr_numeric - Pcr_analytical) / Pcr_analytical

        assert rel_err < 1e-5, (
            f"Euler mismatch L={L}, r={r}: rel_err={rel_err:.3e} "
            f"(Pnum={Pcr_numeric:.6e}, Panal={Pcr_analytical:.6e})"
        )


class TestOrientationInvariance:
    """
    Verify that the buckling load and mode shape are invariant under
    rigid-body rotation of the entire model.
    """

    def test_rotated_cantilever(self):
        E, nu = 1000.0, 0.30
        L = 2.0
        num_nodes = 11
        n_elems = num_nodes - 1

        z = np.linspace(0.0, L, num_nodes)
        node_coords = np.c_[np.zeros_like(z), np.zeros_like(z), z]

        b = 0.08
        h = 0.05
        A = b * h
        Iy = b * h ** 3 / 12.0
        Iz = h * b ** 3 / 12.0
        if b < h:
            b, h = h, b
        J = b * h ** 3 * (1 / 3 - 0.21 * (h / b) * (1 - (h ** 4) / (12 * b ** 4)))
        I_rho = Iy + Iz

        elements = [
            dict(
                node_i=i,
                node_j=i + 1,
                E=E,
                nu=nu,
                A=A,
                I_y=Iy,
                I_z=Iz,
                J=J,
                I_rho=I_rho,
                local_z=np.array([0.0, 1.0, 0.0], dtype=float),
            )
            for i in range(n_elems)
        ]

        boundary_conditions = {0: [True, True, True, True, True, True]}

        P_ref = 1.0
        nodal_loads = {
            n: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0] for n in range(num_nodes)
        }
        nodal_loads[num_nodes - 1][2] = -P_ref

        lam_base, mode_base = elastic_critical_load_analysis(
            node_coords=node_coords,
            elements=elements,
            boundary_conditions=boundary_conditions,
            nodal_loads=nodal_loads,
        )

        # Build rigid rotation R (35 deg about arbitrary axis)
        a = np.array([2.0, -1.0, 0.5], dtype=float)
        a /= np.linalg.norm(a)
        x, y, zax = a
        theta = np.deg2rad(35.0)
        c, s, C = np.cos(theta), np.sin(theta), 1.0 - np.cos(theta)
        R = np.array(
            [
                [c + x * x * C, x * y * C - zax * s, x * zax * C + y * s],
                [y * x * C + zax * s, c + y * y * C, y * zax * C - x * s],
                [zax * x * C - y * s, zax * y * C + x * s, c + zax * zax * C],
            ],
            dtype=float,
        )

        node_coords_rot = (R @ node_coords.T).T

        elements_rot = []
        for e in elements:
            e_rot = dict(e)
            e_rot["local_z"] = R @ e["local_z"]
            elements_rot.append(e_rot)

        F_tip_base = np.array([0.0, 0.0, -P_ref], dtype=float)
        F_tip_rot = R @ F_tip_base
        nodal_loads_rot = {
            n: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0] for n in range(num_nodes)
        }
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

        # Check lambda invariance
        assert np.isfinite(lam_base) and lam_base > 0
        assert np.isfinite(lam_rot) and lam_rot > 0
        assert np.isclose(lam_rot, lam_base, rtol=1e-9, atol=0.0), (
            f"lambda not invariant: base={lam_base:.6e}, rot={lam_rot:.6e}"
        )

        # Check mode transforms correctly
        ndof = 6 * num_nodes
        T = np.zeros((ndof, ndof), dtype=float)
        for n in range(num_nodes):
            bidx = 6 * n
            T[bidx : bidx + 3, bidx : bidx + 3] = R
            T[bidx + 3 : bidx + 6, bidx + 3 : bidx + 6] = R

        mode_expected = T @ mode_base
        free = np.arange(6, ndof, dtype=int)
        v1, v2 = mode_rot[free], mode_expected[free]
        n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
        assert n1 > 0 and n2 > 0, "Degenerate mode."

        v1n, v2n = v1 / n1, v2 / n2
        err = min(np.linalg.norm(v1n - v2n), np.linalg.norm(v1n + v2n))
        assert err < 1e-5, f"Mode mismatch (err={err:.3e})"


class TestMeshConvergence:
    """
    Verify that refining the mesh monotonically improves accuracy and
    the finest mesh achieves high accuracy against Euler buckling.
    """

    def test_convergence(self):
        E, nu = 1000.0, 0.30
        L = 20.0
        r = 1.0
        P_ref = 1.0

        A = np.pi * r ** 2
        I_y = np.pi * r ** 4 / 4.0
        I_z = np.pi * r ** 4 / 4.0
        I_rho = np.pi * r ** 4 / 2.0
        J = np.pi * r ** 4 / 2.0

        Pcr_exact = (np.pi ** 2) * E * I_z / (4.0 * L ** 2)

        meshes = [10, 20, 30, 40]
        rel_errors = []

        for n_elems in meshes:
            n_nodes = n_elems + 1
            z = np.linspace(0.0, L, n_nodes)
            node_coords = np.c_[np.zeros_like(z), np.zeros_like(z), z]

            elements = [
                dict(
                    node_i=i,
                    node_j=i + 1,
                    E=E,
                    nu=nu,
                    A=A,
                    I_y=I_y,
                    I_z=I_z,
                    J=J,
                    I_rho=I_rho,
                    local_z=np.array([1.0, 0.0, 0.0], dtype=float),
                )
                for i in range(n_elems)
            ]

            boundary_conditions = {0: [True, True, True, True, True, True]}
            nodal_loads = {
                n: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0] for n in range(n_nodes)
            }
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

        # monotone improvement
        for i in range(1, len(rel_errors)):
            assert rel_errors[i] <= rel_errors[i - 1] * 1.02 + 1e-12, (
                f"Error did not decrease: {rel_errors[i-1]:.3e} -> "
                f"{rel_errors[i]:.3e} for {meshes[i-1]}->{meshes[i]}"
            )

        # finest mesh accuracy
        assert rel_errors[-1] < 1e-6, (
            f"Finest mesh error too large: {rel_errors[-1]:.3e}"
        )


class TestModelProcessing:
    """
    Verify end-to-end TOML model processing pipeline.
    """

    def test_cantilever_model(self):
        result = subprocess.run(
            ['python3', '/app/process_model.py', '/app/models/cantilever_circular.toml'],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, (
            f"process_model.py failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        output_path = '/app/results/cantilever_circular_result.json'
        assert os.path.exists(output_path), f"Output not found: {output_path}"

        with open(output_path) as f:
            data = json.load(f)

        assert 'critical_load_factor' in data
        assert 'mode_shape' in data
        assert data['n_nodes'] == 11
        assert data['n_elements'] == 10

        # Verify against analytical Euler buckling for this model
        E = 1000.0
        L = 10.0
        r = 0.5
        I = np.pi * r ** 4 / 4.0
        Pcr_analytical = np.pi ** 2 * E * I / (4.0 * L ** 2)

        lam = data['critical_load_factor']
        P_ref = 1.0
        Pcr_numerical = lam * P_ref
        rel_err = abs(Pcr_numerical - Pcr_analytical) / Pcr_analytical

        assert rel_err < 1e-4, (
            f"Model result doesn't match Euler: rel_err={rel_err:.3e}, "
            f"Pcr_num={Pcr_numerical:.6e}, Pcr_ana={Pcr_analytical:.6e}"
        )


class TestOctaveCrossValidation:
    """
    Cross-validate geometric stiffness matrix against independent
    Octave implementation.
    """

    def test_geometric_stiffness_matches_octave(self):
        # Run Octave verification script
        result = subprocess.run(
            ['octave', '--no-gui', '--silent', '/app/octave_ref/verify_kg.m'],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, (
            f"Octave verification script failed (rc={result.returncode}).\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Verify both CSV files were generated
        for case in ['kg_case1.csv', 'kg_case2.csv']:
            path = f'/app/octave_ref/{case}'
            assert os.path.exists(path), f"{case} not generated by Octave script"

        # Load Octave reference matrices
        K1_ref = np.loadtxt('/app/octave_ref/kg_case1.csv', delimiter=',')
        K2_ref = np.loadtxt('/app/octave_ref/kg_case2.csv', delimiter=',')

        assert K1_ref.shape == (12, 12), f"Case 1 shape: {K1_ref.shape}"
        assert K2_ref.shape == (12, 12), f"Case 2 shape: {K2_ref.shape}"

        # Compute with Python implementation
        from frame3d import local_geometric_stiffness_3d_beam

        # Case 1: Pure axial compression
        K1_py = local_geometric_stiffness_3d_beam(
            2.0, 0.01, 5e-6, -1000.0, 0.0, 0.0, 0.0, 0.0, 0.0
        )
        # Case 2: Combined loading
        K2_py = local_geometric_stiffness_3d_beam(
            2.0, 0.01, 5e-6, 500.0, 200.0, 50.0, -75.0, -25.0, 100.0
        )

        # Cross-validate
        assert np.allclose(K1_ref, K1_py, atol=1e-10), (
            f"Case 1 (axial-only) Python/Octave mismatch.\n"
            f"Max diff: {np.max(np.abs(K1_ref - K1_py)):.3e}"
        )
        assert np.allclose(K2_ref, K2_py, atol=1e-10), (
            f"Case 2 (combined) Python/Octave mismatch.\n"
            f"Max diff: {np.max(np.abs(K2_ref - K2_py)):.3e}"
        )
