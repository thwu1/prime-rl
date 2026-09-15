
import json
import os
import pytest


BINARY_PATH = "/app/sbox_engine"
ANSWER_PATH = "/app/answer.json"


def extract_sbox_from_binary(path):
    """Extract the 256-byte S-box permutation from the stripped ELF binary.

    Reads the raw bytes and searches for a contiguous 256-byte block that
    forms a permutation of 0..255.
    """
    with open(path, "rb") as f:
        data = f.read()

    expected = list(range(256))
    for i in range(len(data) - 255):
        candidate = list(data[i : i + 256])
        if sorted(candidate) == expected:
            return candidate

    raise ValueError("No 256-byte permutation block found in binary")


def load_answer():
    with open(ANSWER_PATH) as f:
        return json.load(f)


def int_to_bits(x, n=8):
    """Convert integer to list of bits, LSB first."""
    return [(x >> i) & 1 for i in range(n)]


def bits_to_int(bits):
    """Convert list of bits (LSB first) to integer."""
    return sum(b << i for i, b in enumerate(bits))


def mat_vec_mul_gf2(M, v):
    """Multiply 8x8 GF(2) matrix by 8-bit vector."""
    n = len(M)
    result = []
    for i in range(n):
        val = 0
        for j in range(n):
            val ^= M[i][j] & v[j]
        result.append(val)
    return result


def gf2_det(M):
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
        for row in range(col + 1, n):
            if m[row][col] == 1:
                for j in range(n):
                    m[row][j] ^= m[col][j]
    return 1


class TestSboxDecomposition:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.sbox = extract_sbox_from_binary(BINARY_PATH)
        self.answer = load_answer()
        self.A = self.answer["A"]
        self.B = self.answer["B"]
        self.a = self.answer["a"]
        self.b = self.answer["b"]

    def test_binary_exists(self):
        assert os.path.exists(BINARY_PATH), "sbox_engine binary not found"

    def test_answer_file_exists(self):
        assert os.path.exists(ANSWER_PATH), "answer.json not found"

    def test_sbox_is_permutation(self):
        assert len(self.sbox) == 256
        assert sorted(self.sbox) == list(range(256))

    def test_A_is_8x8_binary(self):
        assert len(self.A) == 8, "A must have 8 rows"
        for i, row in enumerate(self.A):
            assert len(row) == 8, f"A row {i} must have 8 columns"
            for j, val in enumerate(row):
                assert val in (0, 1), f"A[{i}][{j}] must be 0 or 1"

    def test_B_is_8x8_binary(self):
        assert len(self.B) == 8, "B must have 8 rows"
        for i, row in enumerate(self.B):
            assert len(row) == 8, f"B row {i} must have 8 columns"
            for j, val in enumerate(row):
                assert val in (0, 1), f"B[{i}][{j}] must be 0 or 1"

    def test_A_is_invertible(self):
        assert gf2_det(self.A) == 1, "A must be invertible over GF(2)"

    def test_B_is_invertible(self):
        assert gf2_det(self.B) == 1, "B must be invertible over GF(2)"

    def test_a_is_odd(self):
        assert isinstance(self.a, int), "a must be an integer"
        assert 0 < self.a < 256, "a must be in range [1, 255]"
        assert self.a % 2 == 1, "a must be odd (coprime to 256)"

    def test_b_in_range(self):
        assert isinstance(self.b, int), "b must be an integer"
        assert 0 <= self.b < 256, "b must be in range [0, 255]"

    def test_decomposition_correct(self):
        """Verify S(x) = A(X(B(x))) for all x in 0..255."""
        errors = []
        for x in range(256):
            # Apply B
            x_bits = int_to_bits(x)
            bx_bits = mat_vec_mul_gf2(self.B, x_bits)
            bx = bits_to_int(bx_bits)

            # Apply X: arithmetic permutation
            xx = (self.a * bx + self.b) % 256

            # Apply A
            xx_bits = int_to_bits(xx)
            result_bits = mat_vec_mul_gf2(self.A, xx_bits)
            result = bits_to_int(result_bits)

            if result != self.sbox[x]:
                errors.append(x)

        assert len(errors) == 0, (
            f"Decomposition incorrect for {len(errors)} inputs. "
            f"First failures: {errors[:5]}"
        )
