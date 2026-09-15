
import ctypes
import json
import os
import pytest


def load_sbox():
    """Load the S-box from /app/cipher.so via ctypes."""
    lib = ctypes.CDLL("/app/cipher.so")
    lib.strix_sub.restype = ctypes.c_uint8
    lib.strix_sub.argtypes = [ctypes.c_uint8]
    return [lib.strix_sub(i) for i in range(256)]


def load_answer():
    """Load the answer from /app/answer.json."""
    with open("/app/answer.json", "r") as f:
        return json.load(f)


def int_to_bits(x, n=8):
    """Convert integer to list of bits (MSB first)."""
    return [(x >> (n - 1 - i)) & 1 for i in range(n)]


def bits_to_int(bits):
    """Convert list of bits (MSB first) to integer."""
    val = 0
    for b in bits:
        val = (val << 1) | b
    return val


def apply_affine(mat, const, x):
    """Apply affine map: mat * x_bits XOR const, over GF(2)."""
    x_bits = int_to_bits(x)
    result = []
    for i in range(8):
        bit = const[i]
        for j in range(8):
            bit ^= mat[i][j] & x_bits[j]
        result.append(bit)
    return bits_to_int(result)


def mat_det_gf2(M):
    """Compute determinant of 8x8 matrix over GF(2)."""
    n = 8
    m = [row[:] for row in M]
    for col in range(n):
        pivot = -1
        for row in range(col, n):
            if m[row][col] == 1:
                pivot = row
                break
        if pivot == -1:
            return 0
        if pivot != col:
            m[col], m[pivot] = m[pivot], m[col]
        for row in range(n):
            if row != col and m[row][col] == 1:
                for j in range(n):
                    m[row][j] ^= m[col][j]
    return 1


class TestSboxDecomposition:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.sbox = load_sbox()
        self.answer = load_answer()

    def test_answer_file_exists(self):
        assert os.path.exists("/app/answer.json"), "answer.json not found"

    def test_answer_has_required_keys(self):
        required = ["A_mat", "A_const", "B_mat", "B_const", "X_table"]
        for key in required:
            assert key in self.answer, f"Missing key: {key}"

    def test_a_mat_shape(self):
        A = self.answer["A_mat"]
        assert len(A) == 8, "A_mat must have 8 rows"
        for i, row in enumerate(A):
            assert len(row) == 8, f"A_mat row {i} must have 8 elements"
            for j, v in enumerate(row):
                assert v in (0, 1), f"A_mat[{i}][{j}] must be 0 or 1"

    def test_b_mat_shape(self):
        B = self.answer["B_mat"]
        assert len(B) == 8, "B_mat must have 8 rows"
        for i, row in enumerate(B):
            assert len(row) == 8, f"B_mat row {i} must have 8 elements"
            for j, v in enumerate(row):
                assert v in (0, 1), f"B_mat[{i}][{j}] must be 0 or 1"

    def test_a_const_shape(self):
        c = self.answer["A_const"]
        assert len(c) == 8, "A_const must have 8 elements"
        for i, v in enumerate(c):
            assert v in (0, 1), f"A_const[{i}] must be 0 or 1"

    def test_b_const_shape(self):
        c = self.answer["B_const"]
        assert len(c) == 8, "B_const must have 8 elements"
        for i, v in enumerate(c):
            assert v in (0, 1), f"B_const[{i}] must be 0 or 1"

    def test_a_mat_invertible(self):
        det = mat_det_gf2(self.answer["A_mat"])
        assert det == 1, "A_mat is not invertible over GF(2)"

    def test_b_mat_invertible(self):
        det = mat_det_gf2(self.answer["B_mat"])
        assert det == 1, "B_mat is not invertible over GF(2)"

    def test_x_table_is_permutation(self):
        X = self.answer["X_table"]
        assert len(X) == 256, f"X_table must have 256 entries, got {len(X)}"
        assert set(X) == set(range(256)), "X_table is not a permutation of {0,...,255}"

    def test_x_table_is_triangular(self):
        """X must be triangular: X(x) mod 2^k depends only on x mod 2^k."""
        X = self.answer["X_table"]
        for k in range(1, 9):
            mod = 1 << k
            for x in range(256):
                for y in range(256):
                    if x % mod == y % mod:
                        assert X[x] % mod == X[y] % mod, (
                            f"X is not triangular at level k={k}: "
                            f"X({x})={X[x]}, X({y})={X[y]}, "
                            f"but {x} % {mod} == {y} % {mod}"
                        )

    def test_decomposition_correct(self):
        """Verify S(x) = A(X(B(x))) for all x in {0,...,255}."""
        A_mat = self.answer["A_mat"]
        A_const = self.answer["A_const"]
        B_mat = self.answer["B_mat"]
        B_const = self.answer["B_const"]
        X_table = self.answer["X_table"]

        for x in range(256):
            bx = apply_affine(B_mat, B_const, x)
            xx = X_table[bx]
            sx = apply_affine(A_mat, A_const, xx)
            assert sx == self.sbox[x], (
                f"Decomposition failed at x={x}: "
                f"S({x})={self.sbox[x]}, but A(X(B({x})))={sx} "
                f"(B({x})={bx}, X({bx})={xx})"
            )
