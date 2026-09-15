
import math
import sys
import pytest

sys.path.insert(0, "/app")
from ga_engine import (
    mask_tables,
    blade_grade,
    reorder_sign,
    metric,
    geo_product,
    outer_product,
    inner_product,
    reverse_mv,
    grade_project,
    sandwich,
    grade_involution,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def approx(expected, **kw):
    return pytest.approx(expected, abs=1e-9, **kw)


# ---------------------------------------------------------------------------
# mask_tables
# ---------------------------------------------------------------------------

class TestMaskTables:
    def test_dims_1(self):
        mt, inv = mask_tables(1)
        assert list(mt) == [0, 1]
        assert list(inv) == [0, 1]

    def test_dims_2(self):
        mt, inv = mask_tables(2)
        assert list(mt) == [0, 1, 2, 3]
        assert list(inv) == [0, 1, 2, 3]

    def test_dims_3(self):
        mt, inv = mask_tables(3)
        assert list(mt) == [0, 1, 2, 4, 3, 5, 6, 7]
        assert list(inv) == [0, 1, 2, 4, 3, 5, 6, 7]

    def test_dims_4(self):
        mt, inv = mask_tables(4)
        expected_mt = [0, 1, 2, 4, 8, 3, 5, 9, 6, 10, 12, 7, 11, 13, 14, 15]
        expected_inv = [0, 1, 2, 5, 3, 6, 8, 11, 4, 7, 9, 12, 10, 13, 14, 15]
        assert list(mt) == expected_mt
        assert list(inv) == expected_inv

    def test_dims_5(self):
        mt, _ = mask_tables(5)
        # First elements: scalar, then 5 grade-1 blades in order
        assert mt[0] == 0
        assert mt[1:6] == [1, 2, 4, 8, 16]

    def test_roundtrip(self):
        """mask_table and inv_mask_table are inverses."""
        for dims in range(1, 6):
            mt, inv = mask_tables(dims)
            n = 1 << dims
            for i in range(n):
                assert inv[mt[i]] == i
                assert mt[inv[i]] == i

    def test_grade_ordering(self):
        """Blades are sorted by ascending grade."""
        for dims in range(1, 6):
            mt, _ = mask_tables(dims)
            grades = [blade_grade(m) for m in mt]
            assert grades == sorted(grades)


# ---------------------------------------------------------------------------
# blade_grade
# ---------------------------------------------------------------------------

class TestBladeGrade:
    def test_values(self):
        assert blade_grade(0) == 0
        assert blade_grade(1) == 1
        assert blade_grade(2) == 1
        assert blade_grade(3) == 2
        assert blade_grade(7) == 3
        assert blade_grade(15) == 4
        assert blade_grade(0b101010) == 3


# ---------------------------------------------------------------------------
# reorder_sign
# ---------------------------------------------------------------------------

class TestReorderSign:
    def test_identity(self):
        assert reorder_sign(0, 0) == 1
        assert reorder_sign(0, 7) == 1
        assert reorder_sign(5, 0) == 1

    def test_e0_e1(self):
        # e0 * e1 -> +e01, no swap needed
        assert reorder_sign(1, 2) == 1

    def test_e1_e0(self):
        # e1 * e0 -> -e01, one swap
        assert reorder_sign(2, 1) == -1

    def test_e0_e2(self):
        assert reorder_sign(1, 4) == 1

    def test_e2_e0(self):
        # e2 * e0 requires moving e2 past e0: one swap
        assert reorder_sign(4, 1) == -1

    def test_e01_e0(self):
        assert reorder_sign(3, 1) == -1

    def test_e01_e2(self):
        assert reorder_sign(3, 4) == 1

    def test_e012_squared(self):
        # e012 * e012: three pairwise swaps -> odd -> -1
        assert reorder_sign(7, 7) == -1

    def test_e02_squared(self):
        # e02 * e02
        assert reorder_sign(5, 5) == -1

    def test_e13_squared(self):
        # e13 * e13
        assert reorder_sign(10, 10) == -1

    def test_anticommute_pair(self):
        """For any two distinct grade-1 blades, product anticommutes."""
        for i in range(5):
            for j in range(5):
                if i != j:
                    a, b = 1 << i, 1 << j
                    assert reorder_sign(a, b) == -reorder_sign(b, a)

    def test_high_grade_pairs(self):
        # e0123 * e0123 in 4D
        assert reorder_sign(15, 15) == 1  # 4*3/2=6 swaps, even


# ---------------------------------------------------------------------------
# metric
# ---------------------------------------------------------------------------

class TestMetric:
    def test_vga(self):
        for i in range(6):
            assert metric("VGA", i) == 1

    def test_pga(self):
        assert metric("PGA", 0) == 0
        for i in range(1, 6):
            assert metric("PGA", i) == 1

    def test_cl_210(self):
        # Cl(2,1,0): r=0 zero, q=1 negative, p=2 positive
        f = ("Cl", 2, 1, 0)
        assert metric(f, 0) == -1
        assert metric(f, 1) == 1
        assert metric(f, 2) == 1

    def test_cl_111(self):
        # Cl(1,1,1): first 1 zero, next 1 negative, last 1 positive
        f = ("Cl", 1, 1, 1)
        assert metric(f, 0) == 0
        assert metric(f, 1) == -1
        assert metric(f, 2) == 1

    def test_cl_300(self):
        # Cl(3,0,0) == VGA
        f = ("Cl", 3, 0, 0)
        for i in range(3):
            assert metric(f, i) == 1

    def test_cl_012(self):
        # Cl(0,1,2): first 2 zero, next 1 negative, 0 positive
        f = ("Cl", 0, 1, 2)
        assert metric(f, 0) == 0
        assert metric(f, 1) == 0
        assert metric(f, 2) == -1


# ---------------------------------------------------------------------------
# geometric product
# ---------------------------------------------------------------------------

class TestGeoProduct:
    def test_vga_dim2_basic(self):
        # (1 + 2*e0) * (3 + 4*e1) = 3 + 6*e0 + 4*e1 + 8*e01
        a = [1, 2, 0, 0]
        b = [3, 0, 4, 0]
        result = geo_product(a, b, 2, "VGA")
        assert result == approx([3, 6, 4, 8])

    def test_vga_dim3_e0_e1(self):
        # e0 * e1 = +e01
        a = [0, 1, 0, 0, 0, 0, 0, 0]
        b = [0, 0, 1, 0, 0, 0, 0, 0]
        result = geo_product(a, b, 3, "VGA")
        expected = [0, 0, 0, 0, 1, 0, 0, 0]
        assert result == approx(expected)

    def test_vga_dim3_e1_e0(self):
        # e1 * e0 = -e01
        a = [0, 0, 1, 0, 0, 0, 0, 0]
        b = [0, 1, 0, 0, 0, 0, 0, 0]
        result = geo_product(a, b, 3, "VGA")
        expected = [0, 0, 0, 0, -1, 0, 0, 0]
        assert result == approx(expected)

    def test_vga_dim3_e0_squared(self):
        # e0 * e0 = 1 in VGA
        e0 = [0, 1, 0, 0, 0, 0, 0, 0]
        result = geo_product(e0, e0, 3, "VGA")
        expected = [1, 0, 0, 0, 0, 0, 0, 0]
        assert result == approx(expected)

    def test_vga_dim3_e2_e0(self):
        # e2 * e0 = -e02
        a = [0, 0, 0, 1, 0, 0, 0, 0]
        b = [0, 1, 0, 0, 0, 0, 0, 0]
        result = geo_product(a, b, 3, "VGA")
        # e02 is mask 5, position 5 in dim3 table
        expected = [0, 0, 0, 0, 0, -1, 0, 0]
        assert result == approx(expected)

    def test_vga_dim3_pseudoscalar_squared(self):
        # e012 * e012 = -1 in VGA dim=3
        e012 = [0, 0, 0, 0, 0, 0, 0, 1]
        result = geo_product(e012, e012, 3, "VGA")
        expected = [-1, 0, 0, 0, 0, 0, 0, 0]
        assert result == approx(expected)

    def test_pga_dim3_degenerate(self):
        # e0 * e0 = 0 in PGA (e0 is degenerate)
        e0 = [0, 1, 0, 0, 0, 0, 0, 0]
        result = geo_product(e0, e0, 3, "PGA")
        expected = [0, 0, 0, 0, 0, 0, 0, 0]
        assert result == approx(expected)

    def test_pga_dim3_nondegenerate(self):
        # e1 * e1 = 1 in PGA
        e1 = [0, 0, 1, 0, 0, 0, 0, 0]
        result = geo_product(e1, e1, 3, "PGA")
        expected = [1, 0, 0, 0, 0, 0, 0, 0]
        assert result == approx(expected)

    def test_pga_dim3_e0_e1(self):
        # e0 * e1 should produce e01 in PGA (no shared bits, no metric factor)
        a = [0, 1, 0, 0, 0, 0, 0, 0]
        b = [0, 0, 1, 0, 0, 0, 0, 0]
        result = geo_product(a, b, 3, "PGA")
        expected = [0, 0, 0, 0, 1, 0, 0, 0]
        assert result == approx(expected)

    def test_cl210_negative_metric(self):
        # e0 * e0 = -1 in Cl(2,1,0)
        e0 = [0, 1, 0, 0, 0, 0, 0, 0]
        f = ("Cl", 2, 1, 0)
        result = geo_product(e0, e0, 3, f)
        expected = [-1, 0, 0, 0, 0, 0, 0, 0]
        assert result == approx(expected)

    def test_cl210_mixed(self):
        # (e0+e1)*(e0-e1) in Cl(2,1,0): e0^2 + e0*(-e1) + e1*e0 + e1*(-e1)
        #   = -1 + (-e01) + (-e01) + (-1) = -2 - 2*e01
        a = [0, 1, 1, 0, 0, 0, 0, 0]
        b = [0, 1, -1, 0, 0, 0, 0, 0]
        f = ("Cl", 2, 1, 0)
        result = geo_product(a, b, 3, f)
        expected = [-2, 0, 0, 0, -2, 0, 0, 0]
        assert result == approx(expected)

    def test_vga_dim4_complex(self):
        # (1 + e0 + e01 + e0123) * (1 + e1 + e23) in VGA dim=4
        # mask_table(4) positions:
        #   0:scalar, 1:e0, 2:e1, 3:e2, 4:e3,
        #   5:e01, 6:e02, 7:e03, 8:e12, 9:e13, 10:e23,
        #   11:e012, 12:e013, 13:e023, 14:e123, 15:e0123
        a = [0.0] * 16
        a[0] = 1   # scalar
        a[1] = 1   # e0
        a[5] = 1   # e01
        a[15] = 1  # e0123

        b = [0.0] * 16
        b[0] = 1   # scalar
        b[2] = 1   # e1
        b[10] = 1  # e23

        result = geo_product(a, b, 4, "VGA")
        expected = [0.0] * 16
        expected[0] = 1    # scalar
        expected[1] = 2    # e0: 1*e0 + e0*1
        expected[2] = 1    # e1: 1*e1
        expected[5] = 1    # e01: e0*e1 + e01*1
        expected[10] = 1   # e23: 1*e23
        expected[13] = 2   # e023: e0*e23 + e0123*e1
        expected[15] = 2   # e0123: e01*e23 + e0123*1
        assert result == approx(expected)


# ---------------------------------------------------------------------------
# outer product
# ---------------------------------------------------------------------------

class TestOuterProduct:
    def test_e0_wedge_e1(self):
        a = [0, 1, 0, 0, 0, 0, 0, 0]
        b = [0, 0, 1, 0, 0, 0, 0, 0]
        result = outer_product(a, b, 3, "VGA")
        expected = [0, 0, 0, 0, 1, 0, 0, 0]
        assert result == approx(expected)

    def test_e1_wedge_e0(self):
        a = [0, 0, 1, 0, 0, 0, 0, 0]
        b = [0, 1, 0, 0, 0, 0, 0, 0]
        result = outer_product(a, b, 3, "VGA")
        expected = [0, 0, 0, 0, -1, 0, 0, 0]
        assert result == approx(expected)

    def test_e0_wedge_e0(self):
        a = [0, 1, 0, 0, 0, 0, 0, 0]
        result = outer_product(a, a, 3, "VGA")
        expected = [0, 0, 0, 0, 0, 0, 0, 0]
        assert result == approx(expected)

    def test_mixed_grades(self):
        # (1+e0) ^ (1+e1) = 1 + e0 + e1 + e01
        a = [1, 1, 0, 0, 0, 0, 0, 0]
        b = [1, 0, 1, 0, 0, 0, 0, 0]
        result = outer_product(a, b, 3, "VGA")
        expected = [1, 1, 1, 0, 1, 0, 0, 0]
        assert result == approx(expected)

    def test_scalar_wedge_scalar(self):
        a = [2, 0, 0, 0, 0, 0, 0, 0]
        b = [3, 0, 0, 0, 0, 0, 0, 0]
        result = outer_product(a, b, 3, "VGA")
        expected = [6, 0, 0, 0, 0, 0, 0, 0]
        assert result == approx(expected)


# ---------------------------------------------------------------------------
# inner product (Hestenes)
# ---------------------------------------------------------------------------

class TestInnerProduct:
    def test_e0_dot_e0(self):
        # e0 . e0 = 1 in VGA
        a = [0, 1, 0, 0, 0, 0, 0, 0]
        result = inner_product(a, a, 3, "VGA")
        expected = [1, 0, 0, 0, 0, 0, 0, 0]
        assert result == approx(expected)

    def test_e0_dot_e1(self):
        # e0 . e1 = 0 (orthogonal)
        a = [0, 1, 0, 0, 0, 0, 0, 0]
        b = [0, 0, 1, 0, 0, 0, 0, 0]
        result = inner_product(a, b, 3, "VGA")
        expected = [0, 0, 0, 0, 0, 0, 0, 0]
        assert result == approx(expected)

    def test_e01_dot_e0(self):
        # e01 . e0 = -e1 (contraction)
        a = [0, 0, 0, 0, 1, 0, 0, 0]
        b = [0, 1, 0, 0, 0, 0, 0, 0]
        result = inner_product(a, b, 3, "VGA")
        expected = [0, 0, -1, 0, 0, 0, 0, 0]
        assert result == approx(expected)

    def test_e0_dot_e01(self):
        # e0 . e01 = e1
        a = [0, 1, 0, 0, 0, 0, 0, 0]
        b = [0, 0, 0, 0, 1, 0, 0, 0]
        result = inner_product(a, b, 3, "VGA")
        expected = [0, 0, 1, 0, 0, 0, 0, 0]
        assert result == approx(expected)

    def test_scalar_dot_anything_is_zero(self):
        a = [5, 0, 0, 0, 0, 0, 0, 0]
        b = [0, 3, 0, 0, 0, 0, 0, 0]
        result = inner_product(a, b, 3, "VGA")
        assert result == approx([0] * 8)

    def test_e01_dot_e01(self):
        # e01 . e01 = -1 in VGA
        a = [0, 0, 0, 0, 1, 0, 0, 0]
        result = inner_product(a, a, 3, "VGA")
        expected = [-1, 0, 0, 0, 0, 0, 0, 0]
        assert result == approx(expected)

    def test_e012_dot_e01(self):
        # e012 . e01 = -e2
        a = [0, 0, 0, 0, 0, 0, 0, 1]
        b = [0, 0, 0, 0, 1, 0, 0, 0]
        result = inner_product(a, b, 3, "VGA")
        expected = [0, 0, 0, -1, 0, 0, 0, 0]
        assert result == approx(expected)

    def test_e012_dot_e0(self):
        # e012 . e0: grade |3-1|=2. mask(e012)=7, mask(e0)=1.
        # common=1, result_mask=6(e12), gr=2. sign=reorder_sign(7,1)=+1.
        # metric: common bit 0 -> metric(0)=1. met=1.
        # result at inv[6]=6: +1*1*1*1 = +1. So e012.e0 = +e12
        a = [0, 0, 0, 0, 0, 0, 0, 1]
        b = [0, 1, 0, 0, 0, 0, 0, 0]
        result = inner_product(a, b, 3, "VGA")
        expected = [0, 0, 0, 0, 0, 0, 1, 0]
        assert result == approx(expected)


# ---------------------------------------------------------------------------
# reverse
# ---------------------------------------------------------------------------

class TestReverse:
    def test_dim3(self):
        mv_in = [1, 2, 3, 4, 5, 6, 7, 8]
        result = reverse_mv(mv_in, 3)
        # grade 0: +1, grade 1: +1, grade 2: -1, grade 3: -1
        expected = [1, 2, 3, 4, -5, -6, -7, -8]
        assert result == approx(expected)

    def test_dim2(self):
        mv_in = [1, 2, 3, 4]
        result = reverse_mv(mv_in, 2)
        # grade 0: +1, grade 1: +1, grade 2: -1
        expected = [1, 2, 3, -4]
        assert result == approx(expected)

    def test_dim4_grade4_positive(self):
        # grade 4: (-1)^(4*3/2) = (-1)^6 = +1
        mv_in = [0] * 16
        mv_in[15] = 1  # e0123
        result = reverse_mv(mv_in, 4)
        assert result[15] == approx(1)

    def test_dim4_full_pattern(self):
        # Test the complete sign pattern for dim=4
        mv_in = list(range(1, 17))  # 1..16
        result = reverse_mv(mv_in, 4)
        mt, _ = mask_tables(4)
        for i in range(16):
            k = blade_grade(mt[i])
            expected_sign = (-1) ** (k * (k - 1) // 2)
            assert result[i] == approx(expected_sign * mv_in[i])


# ---------------------------------------------------------------------------
# grade_project
# ---------------------------------------------------------------------------

class TestGradeProject:
    def test_dim3_grade0(self):
        mv_in = [1, 2, 3, 4, 5, 6, 7, 8]
        result = grade_project(mv_in, 0, 3)
        expected = [1, 0, 0, 0, 0, 0, 0, 0]
        assert result == approx(expected)

    def test_dim3_grade1(self):
        mv_in = [1, 2, 3, 4, 5, 6, 7, 8]
        result = grade_project(mv_in, 1, 3)
        expected = [0, 2, 3, 4, 0, 0, 0, 0]
        assert result == approx(expected)

    def test_dim3_grade2(self):
        mv_in = [1, 2, 3, 4, 5, 6, 7, 8]
        result = grade_project(mv_in, 2, 3)
        expected = [0, 0, 0, 0, 5, 6, 7, 0]
        assert result == approx(expected)

    def test_dim3_grade3(self):
        mv_in = [1, 2, 3, 4, 5, 6, 7, 8]
        result = grade_project(mv_in, 3, 3)
        expected = [0, 0, 0, 0, 0, 0, 0, 8]
        assert result == approx(expected)


# ---------------------------------------------------------------------------
# property: associativity
# ---------------------------------------------------------------------------

class TestAssociativity:
    def test_vga_dim2(self):
        a = [1, 1, 0, 0]
        b = [0, 0, 1, 0]
        c = [1, 0, 1, 0]
        ab = geo_product(a, b, 2, "VGA")
        ab_c = geo_product(ab, c, 2, "VGA")
        bc = geo_product(b, c, 2, "VGA")
        a_bc = geo_product(a, bc, 2, "VGA")
        assert ab_c == approx(a_bc)

    def test_vga_dim3(self):
        a = [1, 2, -1, 0, 3, 0, 0, 0]
        b = [0, 0, 1, 1, 0, 0, 0, 0]
        c = [-1, 1, 0, 0, 0, 1, 0, 0]
        ab = geo_product(a, b, 3, "VGA")
        ab_c = geo_product(ab, c, 3, "VGA")
        bc = geo_product(b, c, 3, "VGA")
        a_bc = geo_product(a, bc, 3, "VGA")
        assert ab_c == approx(a_bc)

    def test_pga_dim3(self):
        a = [1, 1, 0, 0, 0, 0, 0, 0]
        b = [0, 0, 1, 0, 0, 0, 0, 0]
        c = [0, 0, 0, 1, 0, 0, 0, 0]
        ab = geo_product(a, b, 3, "PGA")
        ab_c = geo_product(ab, c, 3, "PGA")
        bc = geo_product(b, c, 3, "PGA")
        a_bc = geo_product(a, bc, 3, "PGA")
        assert ab_c == approx(a_bc)


# ---------------------------------------------------------------------------
# integration: rotor sandwich product (rotation)
# ---------------------------------------------------------------------------

class TestRotor:
    def test_pi_half_rotation_e0_to_e1(self):
        """Rotate e0 by pi/2 in the e0-e1 plane using a rotor sandwich."""
        c = math.cos(math.pi / 4)
        s = math.sin(math.pi / 4)
        R = [c, 0, 0, 0, -s, 0, 0, 0]
        R_rev = reverse_mv(R, 3)
        e0 = [0, 1, 0, 0, 0, 0, 0, 0]
        temp = geo_product(R, e0, 3, "VGA")
        result = geo_product(temp, R_rev, 3, "VGA")
        expected = [0, 0, 1, 0, 0, 0, 0, 0]
        assert result == approx(expected)

    def test_pi_rotation_e0_to_neg_e0(self):
        c = math.cos(math.pi / 2)
        s = math.sin(math.pi / 2)
        R = [c, 0, 0, 0, -s, 0, 0, 0]
        R_rev = reverse_mv(R, 3)
        e0 = [0, 1, 0, 0, 0, 0, 0, 0]
        temp = geo_product(R, e0, 3, "VGA")
        result = geo_product(temp, R_rev, 3, "VGA")
        expected = [0, -1, 0, 0, 0, 0, 0, 0]
        assert result == approx(expected)

    def test_rotor_norm(self):
        """A rotor has unit norm: R * R~ = 1."""
        c = math.cos(math.pi / 6)
        s = math.sin(math.pi / 6)
        R = [c, 0, 0, 0, -s, 0, 0, 0]
        R_rev = reverse_mv(R, 3)
        norm = geo_product(R, R_rev, 3, "VGA")
        expected = [0.0] * 8
        expected[0] = 1.0
        assert norm == approx(expected)


# ---------------------------------------------------------------------------
# sandwich
# ---------------------------------------------------------------------------

class TestSandwich:
    def test_pi_half_rotation(self):
        """sandwich(R, e0) should rotate e0 to e1."""
        c = math.cos(math.pi / 4)
        s = math.sin(math.pi / 4)
        R = [c, 0, 0, 0, -s, 0, 0, 0]
        e0 = [0, 1, 0, 0, 0, 0, 0, 0]
        result = sandwich(R, e0, 3, "VGA")
        expected = [0, 0, 1, 0, 0, 0, 0, 0]
        assert result == approx(expected)

    def test_identity_rotor(self):
        """Identity rotor (scalar 1) should not change the input."""
        R = [1, 0, 0, 0, 0, 0, 0, 0]
        x = [0, 3, -2, 1, 0, 0, 0, 0]
        result = sandwich(R, x, 3, "VGA")
        assert result == approx(x)

    def test_pi_rotation_preserves_bivector(self):
        """Bivector in the rotation plane is invariant."""
        c = math.cos(math.pi / 2)
        s = math.sin(math.pi / 2)
        R = [c, 0, 0, 0, -s, 0, 0, 0]
        e01 = [0, 0, 0, 0, 1, 0, 0, 0]
        result = sandwich(R, e01, 3, "VGA")
        assert result == approx(e01)

    def test_double_rotation(self):
        """Two pi/4 rotations compose to a pi/2 rotation."""
        c = math.cos(math.pi / 8)
        s = math.sin(math.pi / 8)
        R = [c, 0, 0, 0, -s, 0, 0, 0]
        e0 = [0, 1, 0, 0, 0, 0, 0, 0]
        result = sandwich(R, sandwich(R, e0, 3, "VGA"), 3, "VGA")
        # Two pi/4 rotations = pi/2 total rotation: e0 -> e1
        expected = [0, 0, 1, 0, 0, 0, 0, 0]
        assert result == approx(expected)


# ---------------------------------------------------------------------------
# grade_involution
# ---------------------------------------------------------------------------

class TestGradeInvolution:
    def test_dim3(self):
        mv_in = [1, 2, 3, 4, 5, 6, 7, 8]
        result = grade_involution(mv_in, 3)
        # grade 0: +1, grade 1: -1, grade 2: +1, grade 3: -1
        expected = [1, -2, -3, -4, 5, 6, 7, -8]
        assert result == approx(expected)

    def test_dim2(self):
        mv_in = [1, 2, 3, 4]
        result = grade_involution(mv_in, 2)
        # grade 0: +1, grade 1: -1, grade 2: +1
        expected = [1, -2, -3, 4]
        assert result == approx(expected)

    def test_scalar_unchanged(self):
        mv_in = [5, 0, 0, 0]
        result = grade_involution(mv_in, 2)
        expected = [5, 0, 0, 0]
        assert result == approx(expected)

    def test_involution_is_involution(self):
        """Applying grade involution twice returns the original."""
        mv_in = [1, 2, 3, 4, 5, 6, 7, 8]
        result = grade_involution(grade_involution(mv_in, 3), 3)
        assert result == approx(mv_in)

    def test_dim4_pattern(self):
        """Check all grades in dim 4."""
        mv_in = list(range(1, 17))
        result = grade_involution(mv_in, 4)
        mt, _ = mask_tables(4)
        for i in range(16):
            k = blade_grade(mt[i])
            expected_sign = (-1) ** k
            assert result[i] == approx(expected_sign * mv_in[i])
