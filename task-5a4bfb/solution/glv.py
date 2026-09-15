"""
GLV endomorphism-accelerated scalar multiplication for secp256k1.

Implements the Gallant-Lambert-Vanstone method using:
1. The efficiently-computable endomorphism φ(x,y) = (β·x mod p, y)
2. Lattice-based scalar decomposition k → (k1, k2) with k ≡ k1 + k2·λ (mod n)
3. Shamir's trick for simultaneous double-and-add

β is extracted from the RustCrypto k256 crate (ENDOMORPHISM_BETA in projective.rs).
λ is the scalar eigenvalue satisfying φ(P) = λ·P for all curve points P.

"""

from secp256k1 import P, N, G, point_add, point_neg, point_mul

# ============================================================================
# GLV constants
# ============================================================================

# Endomorphism constant β: a cube root of unity in F_p (β³ ≡ 1 mod p, β ≠ 1).
# Extracted from RustCrypto k256 k256_projective.rs ENDOMORPHISM_BETA:
#   [0x7a, 0xe9, 0x6a, 0x2b, 0x65, 0x7c, 0x07, 0x10,
#    0x6e, 0x64, 0x47, 0x9e, 0xac, 0x34, 0x34, 0xe9,
#    0x9c, 0xf0, 0x49, 0x75, 0x12, 0xf5, 0x89, 0x95,
#    0xc1, 0x39, 0x6c, 0x28, 0x71, 0x95, 0x01, 0xee]
BETA = 0x7ae96a2b657c07106e64479eac3434e99cf0497512f58995c1396c28719501ee

# Scalar eigenvalue λ: a cube root of unity in Z_n (λ³ ≡ 1 mod n, λ ≠ 1).
# Satisfies φ(P) = λ·P for all P on secp256k1, where φ(x,y) = (β·x, y).
# Derived from the relationship: if β is a cube root of unity in F_p,
# then the corresponding eigenvalue λ satisfies λ·G = (β·G_x mod p, G_y).
LAMBDA = 0x5363ad4cc05c30e0a5261c028812645a122e22ea20816678df02967c1b23bd72


# ============================================================================
# Endomorphism
# ============================================================================

def endomorphism(point):
    """
    Apply the secp256k1 curve endomorphism φ(x,y) = (β·x mod p, y).
    Returns None for the identity point.
    """
    if point is None:
        return None
    return ((BETA * point[0]) % P, point[1])


# ============================================================================
# Lattice-based scalar decomposition
# ============================================================================

def _compute_lattice_basis():
    """
    Compute a short basis for the GLV decomposition lattice using the
    half-extended-GCD of (n, λ).

    The lattice L = {(a, b) ∈ Z² : a + b·λ ≡ 0 (mod n)} has the property
    that for any scalar k, the closest lattice point to (k, 0) gives us
    the decomposition k ≡ k1 + k2·λ (mod n) with small k1, k2.

    We run the extended Euclidean algorithm on (N, LAMBDA) and stop when
    the remainder drops below approximately √n ≈ 2^128. The two most
    recent rows give us short lattice vectors.

    Returns (v1, v2) where v1 = (r1, t1) and v2 = (r0, t0) from the
    extended GCD state. The lattice vectors are (r_i, -t_i).
    """
    bound = 1 << 128

    old_r, r = N, LAMBDA
    old_t, t = 0, 1

    while r >= bound:
        q = old_r // r
        old_r, r = r, old_r - q * r
        old_t, t = t, old_t - q * t

    # At this point: r < 2^128, old_r >= 2^128
    # Lattice vectors: v1 = (r, -t), v2 = (old_r, -old_t)
    # where r_i + (-t_i)*λ ≡ 0 mod N (from extended GCD property)
    return (r, t, old_r, old_t)


# Precompute lattice basis
_R1, _T1, _R0, _T0 = _compute_lattice_basis()


def _round_div(a, b):
    """Integer division with rounding to nearest (not truncation)."""
    if b < 0:
        a, b = -a, -b
    return (2 * a + b) // (2 * b)


def decompose_scalar(k):
    """
    Decompose scalar k into (k1, k2) such that:
        k ≡ k1 + k2·λ (mod n)
    with |k1|, |k2| < 2^129 (approximately √n).

    Uses Babai's nearest-plane algorithm with the precomputed short
    lattice basis from the half-GCD.
    """
    k = k % N

    # Lattice vectors: v1 = (a1, b1) = (_R1, -_T1), v2 = (a2, b2) = (_R0, -_T0)
    a1, b1 = _R1, -_T1
    a2, b2 = _R0, -_T0

    # Determinant of the basis matrix
    det = a1 * b2 - b1 * a2

    # Babai's algorithm: express (k, 0) in the lattice basis, round coefficients
    # (k, 0) = c1 * (a1, b1) + c2 * (a2, b2)
    # Solving: c1 = (k*b2 - 0*a2) / det = k*b2/det
    #          c2 = (a1*0 - k*b1) / det = -k*b1/det
    c1 = _round_div(k * b2, det)
    c2 = _round_div(-k * b1, det)

    # Compute the remainder: (k1, k2) = (k, 0) - c1*(a1,b1) - c2*(a2,b2)
    k1 = k - c1 * a1 - c2 * a2
    k2 = 0 - c1 * b1 - c2 * b2

    return (k1, k2)


# ============================================================================
# Shamir's trick (simultaneous double-and-add)
# ============================================================================

def _shamir_trick(k1, p1, k2, p2):
    """
    Compute k1·P1 + k2·P2 using Shamir's trick.

    Scans both scalars' bits simultaneously from MSB to LSB,
    performing one doubling per bit position and adding the
    appropriate precomputed point (P1, P2, or P1+P2).

    This costs ~max(|k1|,|k2|) doublings + additions instead of
    two separate scalar multiplications.
    """
    if k1 == 0 and k2 == 0:
        return None
    if k1 == 0:
        return point_mul(k2, p2) if p2 is not None else None
    if k2 == 0:
        return point_mul(k1, p1) if p1 is not None else None

    # Precompute P1 + P2
    p1p2 = point_add(p1, p2)

    result = None
    bits = max(k1.bit_length(), k2.bit_length())

    for i in range(bits - 1, -1, -1):
        # Double
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
# GLV scalar multiplication
# ============================================================================

def glv_mul(k, point):
    """
    Compute k·P using the GLV endomorphism method.

    1. Decompose k into k1, k2 with k ≡ k1 + k2·λ (mod n)
    2. Compute φ(P) = (β·x mod p, y) — the endomorphism image
    3. If k1 or k2 is negative, negate the corresponding point
    4. Use Shamir's trick to compute k1·P + k2·φ(P)

    Since |k1|, |k2| ≈ 128 bits (vs 256 bits for k), this reduces
    the number of doublings by roughly half, giving ~1.3-1.5x speedup.
    """
    if point is None or k == 0:
        return None
    k = k % N
    if k == 0:
        return None

    k1, k2 = decompose_scalar(k)

    # Set up base points
    p1 = point
    p2 = endomorphism(point)

    # Handle negative sub-scalars via point negation
    if k1 < 0:
        k1 = -k1
        p1 = point_neg(p1)
    if k2 < 0:
        k2 = -k2
        p2 = point_neg(p2)

    return _shamir_trick(k1, p1, k2, p2)
