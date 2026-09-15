
import os
import struct
import random


def _read_poly_bin(path):
    """Read a binary .poly file: 4B magic 'POLY', 4B prime LE, 4B count LE, coefficients LE u32."""
    with open(path, 'rb') as fp:
        magic = fp.read(4)
        assert magic == b'POLY', f"Invalid magic in {path}: got {magic!r}"
        prime, count = struct.unpack('<II', fp.read(8))
        coeffs = list(struct.unpack(f'<{count}I', fp.read(4 * count)))
    return prime, coeffs


def _horner(coeffs, x, mod):
    """Evaluate polynomial at x using Horner's method."""
    result = 0
    for i in range(len(coeffs) - 1, -1, -1):
        result = (result * x + coeffs[i]) % mod
    return result


def test_output_file_exists():
    """The output file must exist at /app/workspace/output/g_final.poly."""
    assert os.path.exists('/app/workspace/output/g_final.poly'), \
        "Output file /app/workspace/output/g_final.poly not found"


def test_valid_binary_format():
    """Output must be a valid .poly binary file with correct prime and coefficient count."""
    P, coeffs = _read_poly_bin('/app/workspace/output/g_final.poly')
    assert P == 998244353, f"Prime mismatch: got {P}, expected 998244353"
    assert len(coeffs) == 65536, f"Expected 65536 coefficients, got {len(coeffs)}"


def test_coefficients_in_valid_range():
    """All coefficients must be in [0, P)."""
    P, coeffs = _read_poly_bin('/app/workspace/output/g_final.poly')
    for i, c in enumerate(coeffs):
        assert 0 <= c < P, f"Coefficient g[{i}] = {c} not in [0, {P})"


def test_constant_term_is_one():
    """g(0) must be the cube root of f(0) = 1, which is 1 since gcd(3, P-1) = 1."""
    P, coeffs = _read_poly_bin('/app/workspace/output/g_final.poly')
    assert coeffs[0] == 1, f"g[0] = {coeffs[0]}, expected 1"


def test_cube_root_identity_random_eval():
    """Verify g(r)^3 == f(r) (mod P) at random evaluation points.

    The input f was constructed as f = h^3 for a polynomial h of degree < N/3,
    so g^3 = f as full polynomials (not just mod x^N). By Schwartz-Zippel,
    an incorrect g passes all 10 checks with negligible probability.
    """
    P_f, f_coeffs = _read_poly_bin('/app/workspace/data/f_input.poly')
    P_g, g_coeffs = _read_poly_bin('/app/workspace/output/g_final.poly')
    assert P_f == P_g, "Prime mismatch between input and output"
    P = P_f

    rng = random.Random(98765)
    for trial in range(10):
        r = rng.randint(2, P - 1)
        f_val = _horner(f_coeffs, r, P)
        g_val = _horner(g_coeffs, r, P)
        g_cubed = pow(g_val, 3, P)
        assert g_cubed == f_val, \
            f"Trial {trial}: g({r})^3 = {g_cubed} != f({r}) = {f_val}"
