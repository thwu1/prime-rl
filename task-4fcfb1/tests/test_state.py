"""
Tests for Gaussian basis rotation pipeline.

"""
import json
import math
import sys

import numpy as np
import pytest

sys.path.insert(0, "/app")


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Section 1: JSON output tests — verify results.json content
# ---------------------------------------------------------------------------


class TestPowerIndices:
    def test_counts(self, results):
        for l in [1, 2, 3, 4]:
            key = f"l_{l}"
            expected_cart = (l + 1) * (l + 2) // 2
            assert results[key]["n_cartesian"] == expected_cart
            assert results[key]["n_spherical"] == 2 * l + 1

    def test_power_sums(self, results):
        for l in [1, 2, 3, 4]:
            for p in results[f"l_{l}"]["powers"]:
                assert sum(p) == l

    def test_ordering(self, results):
        """Powers should be in descending order of first element, then second."""
        for l in [1, 2, 3, 4]:
            powers = results[f"l_{l}"]["powers"]
            for i in range(len(powers) - 1):
                a, b = tuple(powers[i]), tuple(powers[i + 1])
                assert (a[0] > b[0]) or (a[0] == b[0] and a[1] >= b[1])


class TestOverlapMatrix:
    def test_symmetric(self, results):
        for l in [1, 2, 3, 4]:
            S = np.array(results[f"l_{l}"]["overlap_matrix"])
            assert np.allclose(S, S.T, atol=1e-14)

    def test_diagonal_ones(self, results):
        for l in [1, 2, 3, 4]:
            S = np.array(results[f"l_{l}"]["overlap_matrix"])
            assert np.allclose(np.diag(S), np.ones(S.shape[0]), atol=1e-14)

    def test_positive_definite(self, results):
        for l in [1, 2, 3, 4]:
            S = np.array(results[f"l_{l}"]["overlap_matrix"])
            eigenvalues = np.linalg.eigvalsh(S)
            assert all(ev > -1e-14 for ev in eigenvalues)

    def test_l1_identity(self, results):
        S = np.array(results["l_1"]["overlap_matrix"])
        assert np.allclose(S, np.eye(3), atol=1e-14)

    def test_l2_specific_values(self, results):
        S = np.array(results["l_2"]["overlap_matrix"])
        powers = [tuple(p) for p in results["l_2"]["powers"]]
        xx_idx = powers.index((2, 0, 0))
        yy_idx = powers.index((0, 2, 0))
        zz_idx = powers.index((0, 0, 2))
        xy_idx = powers.index((1, 1, 0))
        # xx-yy overlap = 1/3
        assert abs(S[xx_idx, yy_idx] - 1.0 / 3.0) < 1e-14
        # xx-zz overlap = 1/3
        assert abs(S[xx_idx, zz_idx] - 1.0 / 3.0) < 1e-14
        # yy-zz overlap = 1/3
        assert abs(S[yy_idx, zz_idx] - 1.0 / 3.0) < 1e-14
        # xy-xy = 1
        assert abs(S[xy_idx, xy_idx] - 1.0) < 1e-14
        # xy-xx = 0 (odd sum in one axis)
        assert abs(S[xy_idx, xx_idx]) < 1e-14


class TestCartesianRotation:
    def test_preserves_overlap(self, results):
        for l in [1, 2, 3, 4]:
            for rot_name in ["z_rotation_30", "cyclic_permutation"]:
                assert results[f"l_{l}"][rot_name]["preserves_overlap"]

    def test_l1_z_rotation(self, results):
        """For l=1 with standard ordering, R_cart should match the 3x3 rotation."""
        powers = [tuple(p) for p in results["l_1"]["powers"]]
        if powers == [(1, 0, 0), (0, 1, 0), (0, 0, 1)]:
            R_cart = np.array(
                results["l_1"]["z_rotation_30"]["cartesian_rotation"]
            )
            cos30 = math.sqrt(3) / 2
            sin30 = 0.5
            expected = [
                [cos30, -sin30, 0],
                [sin30, cos30, 0],
                [0, 0, 1],
            ]
            assert np.allclose(R_cart, expected, atol=1e-12)

    def test_l2_cyclic_permutation_structure(self, results):
        """Cyclic perm R_cart for l=2 should be a permutation matrix."""
        R_cart = np.array(
            results["l_2"]["cyclic_permutation"]["cartesian_rotation"]
        )
        # Each row and column should have exactly one 1, rest 0
        for row in R_cart:
            assert abs(np.sum(np.abs(row)) - 1.0) < 1e-12
        for col in R_cart.T:
            assert abs(np.sum(np.abs(col)) - 1.0) < 1e-12


class TestCMatrix:
    def test_dimensions(self, results):
        for l in [1, 2, 3, 4]:
            c = np.array(results[f"l_{l}"]["c_matrix"])
            n_sph = 2 * l + 1
            n_cart = (l + 1) * (l + 2) // 2
            assert c.shape == (n_sph, n_cart)

    def test_normalized(self, results):
        for l in [1, 2, 3, 4]:
            assert results[f"l_{l}"]["cScT_is_identity"]


class TestSphericalRotation:
    def test_orthogonal(self, results):
        for l in [1, 2, 3, 4]:
            for rot_name in ["z_rotation_30", "cyclic_permutation"]:
                assert results[f"l_{l}"][rot_name]["is_orthogonal"]

    def test_determinant_one(self, results):
        for l in [1, 2, 3, 4]:
            for rot_name in ["z_rotation_30", "cyclic_permutation"]:
                det = results[f"l_{l}"][rot_name]["determinant"]
                assert abs(det - 1.0) < 1e-10

    def test_z_rotation_trace(self, results):
        """Trace of spherical rotation = character of SO(3) irrep.
        For z-rotation by phi: trace = 1 + 2*sum_{m=1}^{l} cos(m*phi)
        """
        phi = math.pi / 6  # 30 degrees
        expected_traces = {}
        for l in [1, 2, 3, 4]:
            tr = 1.0 + 2.0 * sum(math.cos(m * phi) for m in range(1, l + 1))
            expected_traces[l] = tr

        for l in [1, 2, 3, 4]:
            R_sph = np.array(
                results[f"l_{l}"]["z_rotation_30"]["spherical_rotation"]
            )
            actual_trace = np.trace(R_sph)
            assert abs(actual_trace - expected_traces[l]) < 1e-10, (
                f"l={l}: trace={actual_trace}, expected={expected_traces[l]}"
            )

    def test_cyclic_perm_trace(self, results):
        """For 120-degree rotation: trace = sin((l+0.5)*2pi/3) / sin(pi/3)"""
        phi = 2 * math.pi / 3
        for l in [1, 2, 3, 4]:
            expected = math.sin((l + 0.5) * phi) / math.sin(phi / 2)
            R_sph = np.array(
                results[f"l_{l}"]["cyclic_permutation"]["spherical_rotation"]
            )
            actual_trace = np.trace(R_sph)
            assert abs(actual_trace - expected) < 1e-10, (
                f"l={l}: trace={actual_trace}, expected={expected}"
            )

    def test_z_rotation_c20_invariant(self, results):
        """C_{l,0} (the m=0 component) is invariant under z-rotation."""
        for l in [2, 3, 4]:
            c = np.array(results[f"l_{l}"]["c_matrix"])
            R_sph = np.array(
                results[f"l_{l}"]["z_rotation_30"]["spherical_rotation"]
            )
            powers = [tuple(p) for p in results[f"l_{l}"]["powers"]]
            # Find zz...z (all z) column index
            all_z = (0, 0, l)
            zz_idx = powers.index(all_z)
            # C_{l,0} row has the largest absolute value in the zz column
            c20_row = int(np.argmax(np.abs(c[:, zz_idx])))
            # This row should be invariant: R_sph[c20_row, c20_row] = 1
            assert abs(R_sph[c20_row, c20_row] - 1.0) < 1e-12


class TestGroupProperty:
    def test_composition(self, results):
        for l in [1, 2, 3, 4]:
            assert results["group_property"][f"l_{l}"]


# ---------------------------------------------------------------------------
# Section 2: Direct import tests — anti-cheat verification
# ---------------------------------------------------------------------------


class TestDirectImport:
    """Import gauss_basis directly and test on cases not in config.json."""

    def test_overlap_l5(self):
        """Test overlap matrix for l=5 (not in config)."""
        from gauss_basis import cartesian_powers, overlap_matrix

        S = overlap_matrix(5)
        n = (5 + 1) * (5 + 2) // 2  # 21
        assert S.shape == (n, n)
        assert np.allclose(S, S.T, atol=1e-14)
        assert np.allclose(np.diag(S), np.ones(n), atol=1e-14)
        eigs = np.linalg.eigvalsh(S)
        assert all(ev > -1e-14 for ev in eigs)

    def test_identity_rotation(self):
        """Identity rotation should give identity R_cart."""
        from gauss_basis import cartesian_rotation_matrix, overlap_matrix

        I3 = np.eye(3)
        for l in [1, 2, 3]:
            R_cart = cartesian_rotation_matrix(l, I3)
            n = (l + 1) * (l + 2) // 2
            assert np.allclose(R_cart, np.eye(n), atol=1e-14)

    def test_spherical_l5(self):
        """Full pipeline for l=5 (not in config)."""
        from gauss_basis import (
            overlap_matrix,
            spherical_to_cartesian_matrix,
            spherical_rotation_matrix,
        )

        l = 5
        S = overlap_matrix(l)
        c = spherical_to_cartesian_matrix(l)
        assert c.shape == (2 * l + 1, (l + 1) * (l + 2) // 2)
        cScT = c @ S @ c.T
        assert np.allclose(cScT, np.eye(2 * l + 1), atol=1e-12)

        # 90-degree rotation around y-axis (not in config)
        Ry90 = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], dtype=float)
        R_sph = spherical_rotation_matrix(l, Ry90, c, S)
        assert np.allclose(R_sph.T @ R_sph, np.eye(2 * l + 1), atol=1e-12)
        assert abs(np.linalg.det(R_sph) - 1.0) < 1e-10

        # Trace check for 90-degree rotation
        phi = math.pi / 2
        expected_trace = 1.0 + 2.0 * sum(
            math.cos(m * phi) for m in range(1, l + 1)
        )
        # For y-rotation the character is the same as z-rotation by same angle
        # since trace is invariant under conjugation
        assert abs(np.trace(R_sph) - expected_trace) < 1e-10

    def test_inverse_rotation(self):
        """R(theta) * R(-theta) should equal identity."""
        from gauss_basis import (
            overlap_matrix,
            spherical_to_cartesian_matrix,
            spherical_rotation_matrix,
        )

        l = 3
        S = overlap_matrix(l)
        c = spherical_to_cartesian_matrix(l)

        cos45 = math.sqrt(2) / 2
        sin45 = math.sqrt(2) / 2
        Rz_pos = np.array(
            [[cos45, -sin45, 0], [sin45, cos45, 0], [0, 0, 1]], dtype=float
        )
        Rz_neg = np.array(
            [[cos45, sin45, 0], [-sin45, cos45, 0], [0, 0, 1]], dtype=float
        )

        R_sph_pos = spherical_rotation_matrix(l, Rz_pos, c, S)
        R_sph_neg = spherical_rotation_matrix(l, Rz_neg, c, S)
        product = R_sph_pos @ R_sph_neg
        assert np.allclose(product, np.eye(2 * l + 1), atol=1e-12)
