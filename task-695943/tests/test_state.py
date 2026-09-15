
import ctypes
import json
import os
import sqlite3
import pytest


def int_to_bits(n, width=8):
    """Convert integer to list of bits, LSB first."""
    return [(n >> i) & 1 for i in range(width)]


def bits_to_int(bits):
    """Convert list of bits (LSB first) to integer."""
    return sum(b << i for i, b in enumerate(bits))


def mat_mul_gf2(M, v):
    """Multiply 8x8 GF(2) matrix by 8-bit vector."""
    n = len(M)
    result = [0] * n
    for i in range(n):
        s = 0
        for j in range(n):
            s ^= M[i][j] & v[j]
        result[i] = s
    return result


def mat_det_gf2(M):
    """Compute determinant of matrix over GF(2) via Gaussian elimination."""
    n = len(M)
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


def apply_linear_map(M, x):
    """Apply GF(2) linear map M to integer x."""
    x_bits = int_to_bits(x, 8)
    result_bits = mat_mul_gf2(M, x_bits)
    return bits_to_int(result_bits)


def load_sbox_from_binary():
    """Load the S-box by querying the database and reading the shared library."""
    conn = sqlite3.connect("/app/cipher.db")
    c = conn.cursor()
    c.execute("SELECT value FROM cipher_metadata WHERE param='target_component'")
    symbol_name = c.fetchone()[0]
    conn.close()

    lib = ctypes.CDLL("/app/libcipher.so")
    sbox_arr = (ctypes.c_uint8 * 256).in_dll(lib, symbol_name)
    return list(sbox_arr)


@pytest.fixture
def sbox():
    return load_sbox_from_binary()


@pytest.fixture
def answer():
    with open("/app/answer.json") as f:
        return json.load(f)


class TestAnswerFileExists:
    def test_answer_file_exists(self):
        assert os.path.exists("/app/answer.json"), "answer.json not found"


class TestAnswerFormat:
    def test_has_required_keys(self, answer):
        for key in ["a", "b", "A", "B"]:
            assert key in answer, f"Missing key: {key}"

    def test_a_is_odd(self, answer):
        a = answer["a"]
        assert isinstance(a, int), "a must be an integer"
        assert 1 <= a <= 255, "a must be in [1, 255]"
        assert a % 2 == 1, "a must be odd"

    def test_b_is_valid(self, answer):
        b = answer["b"]
        assert isinstance(b, int), "b must be an integer"
        assert 0 <= b <= 255, "b must be in [0, 255]"

    def test_A_is_8x8_binary(self, answer):
        A = answer["A"]
        assert len(A) == 8, "A must be 8x8"
        for i, row in enumerate(A):
            assert len(row) == 8, f"A row {i} must have 8 elements"
            for j, val in enumerate(row):
                assert val in (0, 1), f"A[{i}][{j}] must be 0 or 1"

    def test_B_is_8x8_binary(self, answer):
        B = answer["B"]
        assert len(B) == 8, "B must be 8x8"
        for i, row in enumerate(B):
            assert len(row) == 8, f"B row {i} must have 8 elements"
            for j, val in enumerate(row):
                assert val in (0, 1), f"B[{i}][{j}] must be 0 or 1"

    def test_A_is_invertible(self, answer):
        assert mat_det_gf2(answer["A"]) == 1, "A must be invertible over GF(2)"

    def test_B_is_invertible(self, answer):
        assert mat_det_gf2(answer["B"]) == 1, "B must be invertible over GF(2)"


class TestDecomposition:
    def test_decomposition_reproduces_sbox(self, sbox, answer):
        """Core test: verify S[x] = A(f(B(x))) for all x."""
        a = answer["a"]
        b = answer["b"]
        A = answer["A"]
        B = answer["B"]

        assert len(sbox) == 256, "S-box must have 256 entries"

        for x in range(256):
            bx = apply_linear_map(B, x)
            fx = (a * bx + b) % 256
            sx = apply_linear_map(A, fx)
            assert sx == sbox[x], (
                f"Decomposition fails at x={x}: "
                f"A(f(B({x}))) = A(f({bx})) = A({fx}) = {sx}, "
                f"but S[{x}] = {sbox[x]}"
            )

    def test_f_is_permutation(self, answer):
        """Verify f(y) = a*y + b mod 256 is a permutation."""
        a = answer["a"]
        b = answer["b"]
        outputs = set()
        for y in range(256):
            fy = (a * y + b) % 256
            outputs.add(fy)
        assert len(outputs) == 256, "f must be a permutation (a must be odd)"
