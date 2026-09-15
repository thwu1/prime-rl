
import json
import pytest


# The weak S-box (table T2) embedded directly for verification
WEAK_SBOX = [
    180, 224, 236, 24, 44, 170, 194, 82, 237, 214, 181, 175, 155, 55, 134, 42,
    212, 68, 27, 89, 250, 47, 131, 132, 84, 29, 172, 229, 209, 152, 251, 192,
    85, 197, 187, 216, 205, 57, 149, 146, 17, 88, 233, 160, 148, 221, 204, 247,
    241, 165, 219, 93, 105, 157, 67, 211, 218, 225, 163, 185, 59, 151, 38, 138,
    13, 110, 227, 115, 35, 36, 123, 143, 95, 22, 167, 238, 122, 65, 34, 107,
    109, 235, 71, 19, 245, 101, 223, 43, 21, 15, 108, 87, 144, 60, 141, 33,
    90, 174, 2, 86, 116, 228, 154, 28, 3, 25, 91, 96, 48, 156, 45, 129,
    173, 239, 98, 242, 53, 50, 76, 153, 26, 83, 226, 171, 77, 118, 103, 46,
    188, 72, 23, 49, 97, 208, 124, 31, 182, 255, 78, 7, 37, 168, 203, 130,
    75, 9, 179, 231, 1, 39, 249, 127, 252, 80, 51, 190, 121, 99, 210, 200,
    14, 136, 246, 162, 54, 16, 120, 58, 92, 240, 178, 63, 111, 117, 196, 222,
    139, 94, 32, 6, 193, 112, 220, 158, 243, 186, 11, 66, 164, 41, 142, 199,
    64, 20, 184, 62, 206, 140, 128, 166, 4, 137, 234, 70, 114, 104, 217, 195,
    150, 176, 61, 232, 106, 40, 119, 198, 189, 244, 69, 12, 56, 113, 18, 159,
    161, 135, 10, 254, 202, 169, 215, 102, 248, 177, 0, 73, 125, 52, 147, 30,
    5, 81, 253, 191, 79, 201, 183, 145, 133, 8, 74, 230, 100, 126, 207, 213,
]

CORRECT_WEAK_ID = 2


def int_to_bits(x, n=8):
    return [(x >> i) & 1 for i in range(n)]


def bits_to_int(bits):
    return sum(b << i for i, b in enumerate(bits))


def mat_vec_gf2(M, v, n=8):
    out = [0] * n
    for i in range(n):
        s = 0
        for j in range(n):
            s ^= M[i][j] & v[j]
        out[i] = s
    return out


def mat_inv_gf2(M, n=8):
    aug = [M[i][:] + [1 if j == i else 0 for j in range(n)] for i in range(n)]
    for col in range(n):
        pivot = -1
        for row in range(col, n):
            if aug[row][col] == 1:
                pivot = row
                break
        if pivot == -1:
            return None
        aug[col], aug[pivot] = aug[pivot], aug[col]
        for row in range(n):
            if row != col and aug[row][col] == 1:
                for j in range(2 * n):
                    aug[row][j] ^= aug[col][j]
    return [aug[i][n:] for i in range(n)]


@pytest.fixture
def findings():
    with open("/app/findings.json", "r") as f:
        data = json.load(f)
    return data


def test_file_exists():
    import os
    assert os.path.exists("/app/findings.json"), "findings.json not found"


def test_json_structure(findings):
    assert "weak_sbox_id" in findings, "Missing key 'weak_sbox_id'"
    assert "decomposition" in findings, "Missing key 'decomposition'"
    d = findings["decomposition"]
    assert "A" in d, "Missing key 'A' in decomposition"
    assert "B" in d, "Missing key 'B' in decomposition"
    assert "a" in d, "Missing key 'a' in decomposition"
    assert "b" in d, "Missing key 'b' in decomposition"


def test_weak_sbox_id(findings):
    assert findings["weak_sbox_id"] == CORRECT_WEAK_ID, (
        f"Incorrect weak S-box ID: got {findings['weak_sbox_id']}, expected {CORRECT_WEAK_ID}"
    )


def test_matrix_dimensions(findings):
    d = findings["decomposition"]
    A = d["A"]
    B = d["B"]
    assert len(A) == 8 and all(len(row) == 8 for row in A), "A must be 8x8"
    assert len(B) == 8 and all(len(row) == 8 for row in B), "B must be 8x8"


def test_matrix_entries_binary(findings):
    d = findings["decomposition"]
    for name, M in [("A", d["A"]), ("B", d["B"])]:
        for i in range(8):
            for j in range(8):
                assert M[i][j] in (0, 1), f"{name}[{i}][{j}] must be 0 or 1"


def test_a_is_odd(findings):
    a = findings["decomposition"]["a"]
    assert isinstance(a, int), "a must be an integer"
    assert 1 <= a <= 255, "a must be in range [1, 255]"
    assert a % 2 == 1, "a must be odd"


def test_b_in_range(findings):
    b = findings["decomposition"]["b"]
    assert isinstance(b, int), "b must be an integer"
    assert 0 <= b <= 255, "b must be in range [0, 255]"


def test_A_invertible(findings):
    A = findings["decomposition"]["A"]
    A_inv = mat_inv_gf2(A)
    assert A_inv is not None, "A must be invertible over GF(2)"


def test_B_invertible(findings):
    B = findings["decomposition"]["B"]
    B_inv = mat_inv_gf2(B)
    assert B_inv is not None, "B must be invertible over GF(2)"


def test_decomposition_correct(findings):
    d = findings["decomposition"]
    A = d["A"]
    B = d["B"]
    a = d["a"]
    b = d["b"]

    for x in range(256):
        v = int_to_bits(x)
        w = mat_vec_gf2(B, v)
        y = bits_to_int(w)
        z = (a * y + b) % 256
        u = int_to_bits(z)
        t = mat_vec_gf2(A, u)
        sx = bits_to_int(t)
        assert sx == WEAK_SBOX[x], (
            f"Decomposition mismatch at x={x}: "
            f"A(f(B({x})))={sx} but S({x})={WEAK_SBOX[x]}"
        )
