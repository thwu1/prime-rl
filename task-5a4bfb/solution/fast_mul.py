"""
Optimized secp256k1 scalar multiplication using the curve endomorphism.

"""

from secp256k1 import P, N, G, point_add, point_neg, point_mul

# ============================================================================
# Constants
# ============================================================================

# Endomorphism constant from RustCrypto k256 ENDOMORPHISM_BETA
BETA = 0x7ae96a2b657c07106e64479eac3434e99cf0497512f58995c1396c28719501ee

# Scalar eigenvalue: the non-trivial cube root of unity mod n
LAMBDA = 0x5363ad4cc05c30e0a5261c028812645a122e22ea20816678df02967c1b23bd72


# ============================================================================
# Endomorphism
# ============================================================================

def endomorphism(point):
    """Apply the secp256k1 curve endomorphism."""
    if point is None:
        return None
    return ((BETA * point[0]) % P, point[1])


# ============================================================================
# Scalar decomposition via half-extended-GCD lattice basis
# ============================================================================

def _compute_lattice_basis():
    """Compute a short basis for the decomposition lattice."""
    bound = 1 << 128

    old_r, r = N, LAMBDA
    old_t, t = 0, 1

    while r >= bound:
        q = old_r // r
        old_r, r = r, old_r - q * r
        old_t, t = t, old_t - q * t

    return (r, t, old_r, old_t)


_R1, _T1, _R0, _T0 = _compute_lattice_basis()


def _round_div(a, b):
    """Integer division with rounding to nearest."""
    if b < 0:
        a, b = -a, -b
    return (2 * a + b) // (2 * b)


def decompose_scalar(k):
    """
    Decompose scalar k into (k1, k2) such that:
        k == k1 + k2 * LAMBDA (mod n)
    with |k1|, |k2| < 2^129.
    """
    k = k % N

    a1, b1 = _R1, -_T1
    a2, b2 = _R0, -_T0

    det = a1 * b2 - b1 * a2

    c1 = _round_div(k * b2, det)
    c2 = _round_div(-k * b1, det)

    k1 = k - c1 * a1 - c2 * a2
    k2 = 0 - c1 * b1 - c2 * b2

    return (k1, k2)


# ============================================================================
# Simultaneous double-and-add
# ============================================================================

def _simultaneous_mul(k1, p1, k2, p2):
    """Compute k1*P1 + k2*P2 scanning both scalars simultaneously."""
    if k1 == 0 and k2 == 0:
        return None
    if k1 == 0:
        return point_mul(k2, p2) if p2 is not None else None
    if k2 == 0:
        return point_mul(k1, p1) if p1 is not None else None

    p1p2 = point_add(p1, p2)

    result = None
    bits = max(k1.bit_length(), k2.bit_length())

    for i in range(bits - 1, -1, -1):
        result = point_add(result, result)

        b1 = (k1 >> i) & 1
        b2 = (k2 >> i) & 1

        if b1 and b2:
            result = point_add(result, p1p2)
        elif b1:
            result = point_add(result, p1)
        elif b2:
            result = point_add(result, p2)

    return result


# ============================================================================
# Optimized scalar multiplication
# ============================================================================

def fast_mul(k, point):
    """Compute k*P using the endomorphism-based optimization."""
    if point is None or k == 0:
        return None
    k = k % N
    if k == 0:
        return None

    k1, k2 = decompose_scalar(k)

    p1 = point
    p2 = endomorphism(point)

    if k1 < 0:
        k1 = -k1
        p1 = point_neg(p1)
    if k2 < 0:
        k2 = -k2
        p2 = point_neg(p2)

    return _simultaneous_mul(k1, p1, k2, p2)
