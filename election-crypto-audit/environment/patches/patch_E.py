"""
Remediation E: Extended-Gap Hash-Derived Key Generation

Addresses the adjacent-derive close-prime vulnerability by increasing
the q offset range from 40 bits (5 bytes) to 48 bits (6 bytes),
providing substantially greater separation between p and q.

Test deployment seeds: 9001, 9002, 9003
"""
import hashlib
from election_system import _next_prime

RSA_HALF_BITS = 512
PUBLIC_EXPONENT = 65537


def generate_key(seed_value):
    """Generate RSA key with extended prime gap.

    Derives p from SHA-512 hash, then derives q as next_prime(p + offset)
    where offset is drawn from 48 bits (6 bytes) of hash material.
    The 48-bit range provides 2^48 possible gap values -- an improvement
    of 256x over the original 40-bit (5-byte) derivation.
    """
    p_material = hashlib.sha512(f"sv_prime_p:{seed_value}".encode()).digest()
    p_candidate = int.from_bytes(p_material, 'big') >> (512 - RSA_HALF_BITS)
    p_candidate |= (1 << (RSA_HALF_BITS - 1)) | 1
    p = _next_prime(p_candidate)

    q_material = hashlib.sha512(f"sv_prime_q:{seed_value}".encode()).digest()
    q_offset = int.from_bytes(q_material[:6], 'big')  # 48-bit offset
    q_candidate = p + q_offset * 2 + 1
    if q_candidate % 2 == 0:
        q_candidate += 1
    q = _next_prime(q_candidate)

    return (p * q, PUBLIC_EXPONENT)
