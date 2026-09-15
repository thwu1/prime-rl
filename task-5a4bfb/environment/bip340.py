"""
BIP340 Schnorr Signatures over secp256k1

Reference: https://github.com/bitcoin/bips/blob/master/bip-0340.mediawiki

"""

import hashlib
from secp256k1 import P, N, G, point_add, point_neg, point_mul, has_even_y


# ============================================================================
# BIP340 tagged hash
# ============================================================================

def tagged_hash(tag, msg):
    """
    Compute BIP340 tagged hash:
    tagged_hash(tag, msg) = SHA256(SHA256(tag) || SHA256(tag) || msg)
    """
    tag_hash = hashlib.sha256(tag).digest()
    return hashlib.sha256(tag_hash + tag_hash + msg).digest()


# ============================================================================
# Utility functions
# ============================================================================

def int_from_bytes(b):
    return int.from_bytes(b, byteorder='big')


def bytes_from_int(x, length=32):
    return x.to_bytes(length, byteorder='big')


def xor_bytes(b0, b1):
    return bytes(a ^ b for a, b in zip(b0, b1))


def lift_x(x_int):
    """Lift x-coordinate to curve point, selecting even y per BIP340."""
    if x_int >= P:
        return None
    y_sq = (pow(x_int, 3, P) + 7) % P
    y = pow(y_sq, (P + 1) // 4, P)
    if pow(y, 2, P) != y_sq:
        return None
    if y % 2 != 0:
        y = P - y
    return (x_int, y)


# ============================================================================
# BIP340 Schnorr signing
# ============================================================================

def schnorr_sign(msg, seckey_bytes, aux_rand):
    """Create a BIP340 Schnorr signature."""
    d0 = int_from_bytes(seckey_bytes)
    if d0 == 0 or d0 >= N:
        return None

    P_point = point_mul(d0, G)
    if P_point is None:
        return None

    d = N - d0 if not has_even_y(P_point) else d0

    t = xor_bytes(bytes_from_int(d), tagged_hash(b"BIP0340/aux", aux_rand))
    rand = tagged_hash(
        b"BIP0340/nonce",
        t + bytes_from_int(P_point[0]) + msg
    )
    k0 = int_from_bytes(rand) % N
    if k0 == 0:
        return None

    R = point_mul(k0, G)
    if R is None:
        return None

    k = N - k0 if not has_even_y(R) else k0

    e_hash = tagged_hash(
        b"BIP0340/challenge",
        bytes_from_int(R[0]) + bytes_from_int(P_point[0]) + msg
    )
    e = int_from_bytes(e_hash) % N

    sig = bytes_from_int(R[0]) + bytes_from_int((k + e * d) % N)
    return sig


# ============================================================================
# BIP340 Schnorr verification
# ============================================================================

def schnorr_verify(msg, pubkey_bytes, sig):
    """Verify a BIP340 Schnorr signature."""
    if len(pubkey_bytes) != 32 or len(sig) != 64:
        return False

    P_point = lift_x(int_from_bytes(pubkey_bytes))
    if P_point is None:
        return False

    r = int_from_bytes(sig[:32])
    s = int_from_bytes(sig[32:])

    if r >= P or s >= N:
        return False

    e_hash = tagged_hash(
        b"BIP0340/challenge",
        sig[:32] + pubkey_bytes + msg
    )
    e = int_from_bytes(e_hash) % N

    R = point_add(point_mul(s, G), point_mul(N - e, P_point))

    if R is None:
        return False
    if not has_even_y(R):
        return False
    if R[0] != r:
        return False

    return True
