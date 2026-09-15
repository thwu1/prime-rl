"""
secp256k1 elliptic curve implementation.

Pure Python implementation of point arithmetic on the secp256k1 curve
(y^2 = x^3 + 7 over F_p).

"""

import hashlib

# ============================================================================
# secp256k1 curve parameters
# ============================================================================

# Field prime: p = 2^256 - 2^32 - 977
P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F

# Curve order
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141

# Generator point coordinates
G_X = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
G_Y = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
G = (G_X, G_Y)


# ============================================================================
# Finite field and elliptic curve point arithmetic
# ============================================================================

def _extended_gcd(a, b):
    """Extended Euclidean Algorithm."""
    if a == 0:
        return b, 0, 1
    g, x, y = _extended_gcd(b % a, a)
    return g, y - (b // a) * x, x


def modinv(a, m):
    """Compute modular inverse of a modulo m using extended GCD."""
    if a < 0:
        a = a % m
    g, x, _ = _extended_gcd(a, m)
    if g != 1:
        return None
    return x % m


def point_add(p1, p2):
    """
    Add two points on secp256k1 (y^2 = x^3 + 7).
    None represents the point at infinity.
    """
    if p1 is None:
        return p2
    if p2 is None:
        return p1

    x1, y1 = p1
    x2, y2 = p2

    if x1 == x2:
        if y1 != y2:
            return None  # P + (-P) = O
        # Point doubling
        lam = (3 * x1 * x1 * modinv(2 * y1, P)) % P
    else:
        lam = ((y2 - y1) * modinv(x2 - x1, P)) % P

    x3 = (lam * lam - x1 - x2) % P
    y3 = (lam * (x1 - x3) - y1) % P
    return (x3, y3)


def point_neg(p):
    """Negate a point on secp256k1."""
    if p is None:
        return None
    return (p[0], (P - p[1]) % P)


def point_mul(k, point):
    """Scalar multiplication via double-and-add (naive, 256-bit scan)."""
    if k == 0 or point is None:
        return None
    k = k % N
    if k == 0:
        return None
    result = None
    addend = point
    while k:
        if k & 1:
            result = point_add(result, addend)
        addend = point_add(addend, addend)
        k >>= 1
    return result


def has_even_y(point):
    """Check if a curve point has even y-coordinate."""
    if point is None:
        return False
    return point[1] % 2 == 0
