
import sys
import math
import subprocess
import pytest

sys.path.insert(0, "/app")
import clifford


# ─── cross-validation against compiled Rust reference ─────────────────

class TestCrossValidation:
    """Cross-validate Python module against the compiled Rust ga_tool binary."""

    @staticmethod
    def _run_tool(*args):
        result = subprocess.run(
            ['/app/reference/ga_tool'] + [str(a) for a in args],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, f"ga_tool failed: {result.stderr}"
        return result.stdout

    @staticmethod
    def _parse_int_list(line):
        """Parse 'label: [1, 2, 3]' → [1, 2, 3]"""
        bracket_content = line.split('[')[1].rstrip(']\n')
        return [int(x.strip()) for x in bracket_content.split(',')]

    def test_mask_tables_3d(self):
        output = self._run_tool('mask_tables', 3)
        lines = output.strip().split('\n')
        ref_mt = self._parse_int_list(lines[0])
        ref_imt = self._parse_int_list(lines[1])
        mt, imt = clifford.mask_tables(3)
        assert mt == ref_mt, f"mask_table(3): {mt} != {ref_mt}"
        assert imt == ref_imt, f"inv_mask_table(3): {imt} != {ref_imt}"

    def test_mask_tables_4d(self):
        output = self._run_tool('mask_tables', 4)
        lines = output.strip().split('\n')
        ref_mt = self._parse_int_list(lines[0])
        mt, _ = clifford.mask_tables(4)
        assert mt == ref_mt

    def test_mask_tables_5d(self):
        output = self._run_tool('mask_tables', 5)
        lines = output.strip().split('\n')
        ref_mt = self._parse_int_list(lines[0])
        mt, _ = clifford.mask_tables(5)
        assert mt == ref_mt

    def test_mask_tables_6d(self):
        output = self._run_tool('mask_tables', 6)
        lines = output.strip().split('\n')
        ref_mt = self._parse_int_list(lines[0])
        ref_imt = self._parse_int_list(lines[1])
        mt, imt = clifford.mask_tables(6)
        assert mt == ref_mt
        assert imt == ref_imt

    def test_metric_vga(self):
        for i in range(4):
            ref = int(self._run_tool('metric', i, 4, 0, 0).strip())
            assert clifford.metric(i, 4, 0, 0) == ref

    def test_metric_cl110(self):
        for i in range(2):
            ref = int(self._run_tool('metric', i, 1, 1, 0).strip())
            assert clifford.metric(i, 1, 1, 0) == ref

    def test_metric_cl201(self):
        for i in range(3):
            ref = int(self._run_tool('metric', i, 2, 0, 1).strip())
            assert clifford.metric(i, 2, 0, 1) == ref

    def test_metric_cl130(self):
        for i in range(4):
            ref = int(self._run_tool('metric', i, 1, 3, 0).strip())
            assert clifford.metric(i, 1, 3, 0) == ref

    def test_metric_cl212(self):
        for i in range(5):
            ref = int(self._run_tool('metric', i, 2, 1, 2).strip())
            assert clifford.metric(i, 2, 1, 2) == ref

    def test_blade_grades_3d(self):
        output = self._run_tool('blade_grades', 3)
        ref_grades = self._parse_int_list(output)
        mt, _ = clifford.mask_tables(3)
        py_grades = [bin(m).count('1') for m in mt]
        assert py_grades == ref_grades

    def test_blade_grades_5d(self):
        output = self._run_tool('blade_grades', 5)
        ref_grades = self._parse_int_list(output)
        mt, _ = clifford.mask_tables(5)
        py_grades = [bin(m).count('1') for m in mt]
        assert py_grades == ref_grades


# ─── mask_tables ──────────────────────────────────────────────────────

class TestMaskTables:
    def test_dims_1(self):
        mt, imt = clifford.mask_tables(1)
        assert mt == [0, 1]
        assert imt == [0, 1]

    def test_dims_2(self):
        mt, imt = clifford.mask_tables(2)
        assert mt == [0, 1, 2, 3]
        assert imt == [0, 1, 2, 3]

    def test_dims_3(self):
        mt, imt = clifford.mask_tables(3)
        assert mt == [0, 1, 2, 4, 3, 5, 6, 7]
        assert imt == [0, 1, 2, 4, 3, 5, 6, 7]

    def test_dims_4(self):
        mt, imt = clifford.mask_tables(4)
        assert mt == [0, 1, 2, 4, 8, 3, 5, 9, 6, 10, 12, 7, 11, 13, 14, 15]
        assert imt == [0, 1, 2, 5, 3, 6, 8, 11, 4, 7, 9, 12, 10, 13, 14, 15]

    def test_dims_5(self):
        mt, _ = clifford.mask_tables(5)
        expected = [
            0, 1, 2, 4, 8, 16,
            3, 5, 9, 17, 6, 10, 18, 12, 20, 24,
            7, 11, 19, 13, 21, 25, 14, 22, 26, 28,
            15, 23, 27, 29, 30,
            31,
        ]
        assert mt == expected

    def test_invertibility(self):
        """mask_table and inv_mask_table are mutual inverses."""
        for dims in range(1, 7):
            mt, imt = clifford.mask_tables(dims)
            n = 1 << dims
            assert len(mt) == n
            assert len(imt) == n
            for i in range(n):
                assert imt[mt[i]] == i, f"dims={dims}, i={i}"
                assert mt[imt[i]] == i, f"dims={dims}, i={i}"

    def test_grade_ordering(self):
        """Blades are ordered by grade (ascending)."""
        for dims in range(1, 7):
            mt, _ = clifford.mask_tables(dims)
            grades = [bin(m).count("1") for m in mt]
            assert grades == sorted(grades), f"dims={dims}: not sorted by grade"


# ─── metric ───────────────────────────────────────────────────────────

class TestMetric:
    def test_vga(self):
        for i in range(3):
            assert clifford.metric(i, 3, 0, 0) == 1

    def test_split_complex(self):
        # Cl(1,1,0): dim 0 → -1, dim 1 → +1
        assert clifford.metric(0, 1, 1, 0) == -1
        assert clifford.metric(1, 1, 1, 0) == 1

    def test_degenerate(self):
        # Cl(2,0,1): dim 0 → 0, dims 1,2 → +1
        assert clifford.metric(0, 2, 0, 1) == 0
        assert clifford.metric(1, 2, 0, 1) == 1
        assert clifford.metric(2, 2, 0, 1) == 1

    def test_sta(self):
        # Cl(1,3,0): dims 0-2 → -1, dim 3 → +1
        assert clifford.metric(0, 1, 3, 0) == -1
        assert clifford.metric(1, 1, 3, 0) == -1
        assert clifford.metric(2, 1, 3, 0) == -1
        assert clifford.metric(3, 1, 3, 0) == 1

    def test_mixed(self):
        # Cl(2,1,2): dims 0,1 → 0; dim 2 → -1; dims 3,4 → +1
        assert clifford.metric(0, 2, 1, 2) == 0
        assert clifford.metric(1, 2, 1, 2) == 0
        assert clifford.metric(2, 2, 1, 2) == -1
        assert clifford.metric(3, 2, 1, 2) == 1
        assert clifford.metric(4, 2, 1, 2) == 1


# ─── basis vector products ────────────────────────────────────────────

class TestBasisProducts:
    @staticmethod
    def _basis_vector(dims, index):
        _, imt = clifford.mask_tables(dims)
        mv = [0.0] * (1 << dims)
        mv[imt[1 << index]] = 1.0
        return mv

    @staticmethod
    def _scalar(dims, value):
        mv = [0.0] * (1 << dims)
        mv[0] = float(value)
        return mv

    def test_self_product_vga(self):
        dims, p, q, r = 3, 3, 0, 0
        for i in range(dims):
            ei = self._basis_vector(dims, i)
            result = clifford.geo_product(ei, ei, dims, p, q, r)
            expected = self._scalar(dims, 1.0)
            for k in range(len(result)):
                assert abs(result[k] - expected[k]) < 1e-12, \
                    f"e_{i}^2 failed at component {k} in Cl(3,0,0)"

    def test_self_product_mixed(self):
        dims, p, q, r = 2, 1, 1, 0
        e0 = self._basis_vector(dims, 0)
        e1 = self._basis_vector(dims, 1)
        r0 = clifford.geo_product(e0, e0, dims, p, q, r)
        r1 = clifford.geo_product(e1, e1, dims, p, q, r)
        assert abs(r0[0] - (-1.0)) < 1e-12, "e_0^2 should be -1 in Cl(1,1,0)"
        assert all(abs(r0[k]) < 1e-12 for k in range(1, 4))
        assert abs(r1[0] - 1.0) < 1e-12, "e_1^2 should be +1 in Cl(1,1,0)"
        assert all(abs(r1[k]) < 1e-12 for k in range(1, 4))

    def test_self_product_degenerate(self):
        dims, p, q, r = 3, 2, 0, 1
        e0 = self._basis_vector(dims, 0)
        result = clifford.geo_product(e0, e0, dims, p, q, r)
        assert all(abs(c) < 1e-12 for c in result), "e_0^2 should be 0 in Cl(2,0,1)"

    def test_anticommutativity(self):
        dims, p, q, r = 3, 3, 0, 0
        for i in range(dims):
            for j in range(i + 1, dims):
                ei = self._basis_vector(dims, i)
                ej = self._basis_vector(dims, j)
                r1 = clifford.geo_product(ei, ej, dims, p, q, r)
                r2 = clifford.geo_product(ej, ei, dims, p, q, r)
                for k in range(len(r1)):
                    assert abs(r1[k] + r2[k]) < 1e-12, \
                        f"Anticommutativity failed for e_{i}*e_{j} at component {k}"

    def test_anticommutativity_4d(self):
        dims, p, q, r = 4, 4, 0, 0
        for i in range(dims):
            for j in range(i + 1, dims):
                ei = self._basis_vector(dims, i)
                ej = self._basis_vector(dims, j)
                r1 = clifford.geo_product(ei, ej, dims, p, q, r)
                r2 = clifford.geo_product(ej, ei, dims, p, q, r)
                for k in range(len(r1)):
                    assert abs(r1[k] + r2[k]) < 1e-12, \
                        f"Anticommutativity failed for e_{i}*e_{j} at {k} in 4D"


# ─── geometric product ────────────────────────────────────────────────

class TestGeoProduct:
    @staticmethod
    def _approx_eq(a, b, tol=1e-10):
        assert len(a) == len(b), f"Length mismatch: {len(a)} vs {len(b)}"
        for i in range(len(a)):
            assert abs(a[i] - b[i]) < tol, f"Component {i}: {a[i]} != {b[i]}"

    def test_vga_3d(self):
        # (1 + 2e0 + 3e1 + 4e2) * (5 + 6e0 + 7e1 + 8e2) in Cl(3,0,0)
        A = [1.0, 2, 3, 4, 0, 0, 0, 0]
        B = [5.0, 6, 7, 8, 0, 0, 0, 0]
        result = clifford.geo_product(A, B, 3, 3, 0, 0)
        expected = [70.0, 16, 22, 28, -4, -8, -4, 0]
        self._approx_eq(result, expected)

    def test_split_complex(self):
        # (1+e0+e1+e01) * (2+3e0+4e1+5e01) in Cl(1,1,0)
        A = [1.0, 1, 1, 1]
        B = [2.0, 3, 4, 5]
        result = clifford.geo_product(A, B, 2, 1, 1, 0)
        expected = [8.0, 4, 4, 8]
        self._approx_eq(result, expected)

    def test_degenerate(self):
        # (1 + 2e0 + 3e1) * (4 + 5e0 + 6e1) in Cl(2,0,1)
        A = [1.0, 2, 3, 0, 0, 0, 0, 0]
        B = [4.0, 5, 6, 0, 0, 0, 0, 0]
        result = clifford.geo_product(A, B, 3, 2, 0, 1)
        expected = [22.0, 13, 18, 0, -3, 0, 0, 0]
        self._approx_eq(result, expected)

    def test_scalar_identity(self):
        # 1 * A = A
        dims, p, q, r = 3, 3, 0, 0
        A = [1.0, 2, 3, 4, 5, 6, 7, 8]
        one = [1.0, 0, 0, 0, 0, 0, 0, 0]
        r1 = clifford.geo_product(one, A, dims, p, q, r)
        r2 = clifford.geo_product(A, one, dims, p, q, r)
        self._approx_eq(r1, A)
        self._approx_eq(r2, A)

    def test_associativity(self):
        import random
        random.seed(42)
        dims, p, q, r = 3, 3, 0, 0
        n = 1 << dims
        for trial in range(5):
            A = [random.uniform(-5, 5) for _ in range(n)]
            B = [random.uniform(-5, 5) for _ in range(n)]
            C = [random.uniform(-5, 5) for _ in range(n)]
            AB = clifford.geo_product(A, B, dims, p, q, r)
            AB_C = clifford.geo_product(AB, C, dims, p, q, r)
            BC = clifford.geo_product(B, C, dims, p, q, r)
            A_BC = clifford.geo_product(A, BC, dims, p, q, r)
            for k in range(n):
                assert abs(AB_C[k] - A_BC[k]) < 1e-8, \
                    f"Associativity trial {trial} component {k}: {AB_C[k]} vs {A_BC[k]}"

    def test_associativity_mixed_metric(self):
        import random
        random.seed(99)
        dims, p, q, r = 3, 2, 0, 1
        n = 1 << dims
        for trial in range(3):
            A = [random.uniform(-3, 3) for _ in range(n)]
            B = [random.uniform(-3, 3) for _ in range(n)]
            C = [random.uniform(-3, 3) for _ in range(n)]
            AB = clifford.geo_product(A, B, dims, p, q, r)
            AB_C = clifford.geo_product(AB, C, dims, p, q, r)
            BC = clifford.geo_product(B, C, dims, p, q, r)
            A_BC = clifford.geo_product(A, BC, dims, p, q, r)
            for k in range(n):
                assert abs(AB_C[k] - A_BC[k]) < 1e-8, \
                    f"Assoc (Cl201) trial {trial} at {k}: {AB_C[k]} vs {A_BC[k]}"


# ─── outer product ────────────────────────────────────────────────────

class TestOuterProduct:
    def test_basis_vectors(self):
        """e1 ∧ e2 = e12 in 3D VGA."""
        dims, p, q, r = 3, 3, 0, 0
        _, imt = clifford.mask_tables(dims)
        e1 = [0.0] * 8
        e1[imt[2]] = 1.0   # e_1 has bitmask 0b010
        e2 = [0.0] * 8
        e2[imt[4]] = 1.0   # e_2 has bitmask 0b100
        result = clifford.outer_product(e1, e2, dims, p, q, r)
        expected = [0.0] * 8
        expected[imt[6]] = 1.0  # e_12 has bitmask 0b110
        for i in range(8):
            assert abs(result[i] - expected[i]) < 1e-12

    def test_anticomm_wedge(self):
        """e1 ∧ e2 = -(e2 ∧ e1)."""
        dims, p, q, r = 3, 3, 0, 0
        _, imt = clifford.mask_tables(dims)
        e1 = [0.0] * 8
        e1[imt[2]] = 1.0
        e2 = [0.0] * 8
        e2[imt[4]] = 1.0
        r1 = clifford.outer_product(e1, e2, dims, p, q, r)
        r2 = clifford.outer_product(e2, e1, dims, p, q, r)
        for i in range(8):
            assert abs(r1[i] + r2[i]) < 1e-12

    def test_self_wedge_zero(self):
        """v ∧ v = 0 for a pure vector."""
        dims, p, q, r = 3, 3, 0, 0
        v = [0.0, 1, 2, 3, 0, 0, 0, 0]
        result = clifford.outer_product(v, v, dims, p, q, r)
        for c in result:
            assert abs(c) < 1e-12, f"v ∧ v should be 0, got component {c}"

    def test_trivector_wedge(self):
        """e0 ∧ e1 ∧ e2 = e012 via two wedges."""
        dims, p, q, r = 3, 3, 0, 0
        _, imt = clifford.mask_tables(dims)
        e0 = [0.0] * 8
        e0[imt[1]] = 1.0
        e1 = [0.0] * 8
        e1[imt[2]] = 1.0
        e2 = [0.0] * 8
        e2[imt[4]] = 1.0
        e01 = clifford.outer_product(e0, e1, dims, p, q, r)
        e012 = clifford.outer_product(e01, e2, dims, p, q, r)
        expected = [0.0] * 8
        expected[imt[7]] = 1.0  # e_012 has bitmask 0b111
        for i in range(8):
            assert abs(e012[i] - expected[i]) < 1e-12


# ─── inner product (left contraction) ─────────────────────────────────

class TestInnerProduct:
    def test_vector_bivector(self):
        """e1 ⌋ e12 = e2 in 3D VGA."""
        dims, p, q, r = 3, 3, 0, 0
        _, imt = clifford.mask_tables(dims)
        e1 = [0.0] * 8
        e1[imt[2]] = 1.0     # e_1
        e12 = [0.0] * 8
        e12[imt[6]] = 1.0    # e_12
        result = clifford.inner_product(e1, e12, dims, p, q, r)
        expected = [0.0] * 8
        expected[imt[4]] = 1.0  # e_2
        for i in range(8):
            assert abs(result[i] - expected[i]) < 1e-12, \
                f"e1 ⌋ e12 at {i}: {result[i]} vs {expected[i]}"

    def test_contraction_sign(self):
        """e2 ⌋ e12 = -e1 in 3D VGA."""
        dims, p, q, r = 3, 3, 0, 0
        _, imt = clifford.mask_tables(dims)
        e2 = [0.0] * 8
        e2[imt[4]] = 1.0     # e_2
        e12 = [0.0] * 8
        e12[imt[6]] = 1.0    # e_12
        result = clifford.inner_product(e2, e12, dims, p, q, r)
        expected = [0.0] * 8
        expected[imt[2]] = -1.0  # -e_1
        for i in range(8):
            assert abs(result[i] - expected[i]) < 1e-12, \
                f"e2 ⌋ e12 at {i}: {result[i]} vs {expected[i]}"

    def test_scalar_contraction(self):
        """Scalar left-contracts to the identity: 1 ⌋ A = A for scalar 1."""
        dims, p, q, r = 3, 3, 0, 0
        one = [1.0, 0, 0, 0, 0, 0, 0, 0]
        A = [1.0, 2, 3, 4, 5, 6, 7, 8]
        result = clifford.inner_product(one, A, dims, p, q, r)
        for i in range(8):
            assert abs(result[i] - A[i]) < 1e-12

    def test_vector_dot_vector(self):
        """Dot product of two vectors via left contraction gives scalar."""
        dims, p, q, r = 3, 3, 0, 0
        a = [0.0, 2, 3, 4, 0, 0, 0, 0]  # 2e0 + 3e1 + 4e2
        b = [0.0, 5, 6, 7, 0, 0, 0, 0]  # 5e0 + 6e1 + 7e2
        result = clifford.inner_product(a, b, dims, p, q, r)
        # Dot product = 2*5 + 3*6 + 4*7 = 10+18+28 = 56
        assert abs(result[0] - 56.0) < 1e-10
        for i in range(1, 8):
            assert abs(result[i]) < 1e-12


# ─── grade projection ─────────────────────────────────────────────────

class TestGradeProject:
    def test_grades_3d(self):
        dims = 3
        mv = [1.0, 2, 3, 4, 5, 6, 7, 8]
        g0 = clifford.grade_project(mv, dims, 0)
        g1 = clifford.grade_project(mv, dims, 1)
        g2 = clifford.grade_project(mv, dims, 2)
        g3 = clifford.grade_project(mv, dims, 3)
        assert g0 == [1, 0, 0, 0, 0, 0, 0, 0]
        assert g1 == [0, 2, 3, 4, 0, 0, 0, 0]
        assert g2 == [0, 0, 0, 0, 5, 6, 7, 0]
        assert g3 == [0, 0, 0, 0, 0, 0, 0, 8]

    def test_sum_of_projections(self):
        """Sum of all grade projections equals the original."""
        dims = 4
        n = 1 << dims
        mv = [float(i + 1) for i in range(n)]
        total = [0.0] * n
        for g in range(dims + 1):
            proj = clifford.grade_project(mv, dims, g)
            for k in range(n):
                total[k] += proj[k]
        for k in range(n):
            assert abs(total[k] - mv[k]) < 1e-12


# ─── reverse ──────────────────────────────────────────────────────────

class TestReverse:
    def test_reverse_3d(self):
        dims = 3
        mv = [1.0, 2, 3, 4, 5, 6, 7, 8]
        result = clifford.reverse_mv(mv, dims)
        # grade 0 → +1, grade 1 → +1, grade 2 → -1, grade 3 → -1
        expected = [1.0, 2, 3, 4, -5, -6, -7, -8]
        assert result == expected

    def test_reverse_4d(self):
        dims = 4
        n = 1 << dims
        mv = [float(i + 1) for i in range(n)]
        result = clifford.reverse_mv(mv, dims)
        mt, _ = clifford.mask_tables(dims)
        for i in range(n):
            grade = bin(mt[i]).count("1")
            sign = (-1) ** (grade * (grade - 1) // 2)
            assert result[i] == sign * mv[i], \
                f"Reverse 4D failed at idx {i} (grade {grade})"

    def test_reverse_involution(self):
        """Reverse applied twice = identity."""
        dims = 3
        mv = [1.0, 2, 3, 4, 5, 6, 7, 8]
        result = clifford.reverse_mv(clifford.reverse_mv(mv, dims), dims)
        for i in range(8):
            assert abs(result[i] - mv[i]) < 1e-12


# ─── sandwich product ─────────────────────────────────────────────────

class TestSandwich:
    def test_rotation_e1(self):
        """Rotate e_1 by pi/3 in the e_1-e_2 plane."""
        dims, p, q, r = 3, 3, 0, 0
        _, imt = clifford.mask_tables(dims)
        theta = math.pi / 3
        R = [0.0] * 8
        R[0] = math.cos(theta / 2)       # scalar part
        R[imt[6]] = math.sin(theta / 2)  # e_12 part (bitmask 0b110)
        v = [0.0] * 8
        v[imt[2]] = 1.0  # e_1
        result = clifford.sandwich(R, v, dims, p, q, r)
        expected = [0.0] * 8
        expected[imt[2]] = math.cos(theta)   # cos(60°)*e_1
        expected[imt[4]] = -math.sin(theta)  # -sin(60°)*e_2
        for i in range(8):
            assert abs(result[i] - expected[i]) < 1e-10, \
                f"Rotation at {i}: {result[i]} vs {expected[i]}"

    def test_rotation_preserves_norm(self):
        """Sandwich product preserves the squared norm of a vector."""
        dims, p, q, r = 3, 3, 0, 0
        _, imt = clifford.mask_tables(dims)
        theta = 1.23
        R = [0.0] * 8
        R[0] = math.cos(theta / 2)
        R[imt[6]] = math.sin(theta / 2)
        v = [0.0] * 8
        v[imt[1]] = 3.0
        v[imt[2]] = -1.0
        v[imt[4]] = 2.0
        result = clifford.sandwich(R, v, dims, p, q, r)
        # Squared norm of v: 9 + 1 + 4 = 14
        norm_before = sum(c * c for c in v)
        norm_after = sum(c * c for c in result)
        assert abs(norm_before - norm_after) < 1e-10

    def test_identity_sandwich(self):
        """Sandwich with identity rotor (R=1) returns original."""
        dims, p, q, r = 3, 3, 0, 0
        R = [1.0, 0, 0, 0, 0, 0, 0, 0]
        v = [0.0, 1, 2, 3, 0, 0, 0, 0]
        result = clifford.sandwich(R, v, dims, p, q, r)
        for i in range(8):
            assert abs(result[i] - v[i]) < 1e-10


# ─── exp_bivector ──────────────────────────────────────────────────────

class TestExpBivector:
    def test_elliptic(self):
        """exp(θ/2 * e_12) in VGA → rotation rotor."""
        dims, p, q, r = 3, 3, 0, 0
        _, imt = clifford.mask_tables(dims)
        theta = math.pi / 3
        B = [0.0] * 8
        B[imt[6]] = theta / 2  # e_12 component
        result = clifford.exp_bivector(B, dims, p, q, r)
        expected = [0.0] * 8
        expected[0] = math.cos(theta / 2)
        expected[imt[6]] = math.sin(theta / 2)
        for i in range(8):
            assert abs(result[i] - expected[i]) < 1e-10, \
                f"Elliptic exp at {i}: {result[i]} vs {expected[i]}"

    def test_hyperbolic(self):
        """exp(t * e_01) in Cl(1,1,0) → hyperbolic rotor."""
        dims, p, q, r = 2, 1, 1, 0
        _, imt = clifford.mask_tables(dims)
        t = 1.0
        B = [0.0] * 4
        B[imt[3]] = t  # e_01
        result = clifford.exp_bivector(B, dims, p, q, r)
        expected = [0.0] * 4
        expected[0] = math.cosh(t)
        expected[imt[3]] = math.sinh(t)
        for i in range(4):
            assert abs(result[i] - expected[i]) < 1e-10, \
                f"Hyperbolic exp at {i}: {result[i]} vs {expected[i]}"

    def test_null(self):
        """exp(t * e_01) in Cl(2,0,1) → 1 + t*e_01 (null bivector)."""
        dims, p, q, r = 3, 2, 0, 1
        _, imt = clifford.mask_tables(dims)
        t = 2.0
        B = [0.0] * 8
        B[imt[3]] = t  # e_01
        result = clifford.exp_bivector(B, dims, p, q, r)
        expected = [0.0] * 8
        expected[0] = 1.0
        expected[imt[3]] = t
        for i in range(8):
            assert abs(result[i] - expected[i]) < 1e-10, \
                f"Null exp at {i}: {result[i]} vs {expected[i]}"

    def test_zero_bivector(self):
        """exp(0) = 1."""
        dims, p, q, r = 3, 3, 0, 0
        B = [0.0] * 8
        result = clifford.exp_bivector(B, dims, p, q, r)
        expected = [0.0] * 8
        expected[0] = 1.0
        for i in range(8):
            assert abs(result[i] - expected[i]) < 1e-10

    def test_exp_then_sandwich(self):
        """Build rotor via exp_bivector, then apply via sandwich."""
        dims, p, q, r = 3, 3, 0, 0
        _, imt = clifford.mask_tables(dims)
        theta = math.pi / 4
        B = [0.0] * 8
        B[imt[6]] = theta / 2  # rotation angle/2 in e_12 plane
        R = clifford.exp_bivector(B, dims, p, q, r)
        v = [0.0] * 8
        v[imt[2]] = 1.0  # e_1
        result = clifford.sandwich(R, v, dims, p, q, r)
        expected = [0.0] * 8
        expected[imt[2]] = math.cos(theta)
        expected[imt[4]] = -math.sin(theta)
        for i in range(8):
            assert abs(result[i] - expected[i]) < 1e-10, \
                f"exp→sandwich at {i}: {result[i]} vs {expected[i]}"
