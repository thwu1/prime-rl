"""
Remediation D: Independent Hash-Derived Key Generation

Fixes the adjacent-derive vulnerability by deriving both primes from
fully independent SHA-512 hashes with distinct domain separators.
Eliminates the close-prime relationship entirely.

Test deployment seeds: 8001, 8002, 8003
"""
import hashlib
from election_system import _next_prime

RSA_HALF_BITS = 512
PUBLIC_EXPONENT = 65537


def generate_key(seed_value):
    """Generate RSA key with independently hash-derived primes.

    Both p and q are derived from SHA-512 hashes of the seed with different
    domain separators. Unlike the original adjacent_derive, q is NOT derived
    as an offset from p -- both primes are fully independent.
    """
    p_material = hashlib.sha512(f"independent_p:{seed_value}".encode()).digest()
    p_candidate = int.from_bytes(p_material, 'big') >> (512 - RSA_HALF_BITS)
    p_candidate |= (1 << (RSA_HALF_BITS - 1)) | 1
    p = _next_prime(p_candidate)

    q_material = hashlib.sha512(f"independent_q:{seed_value}".encode()).digest()
    q_candidate = int.from_bytes(q_material, 'big') >> (512 - RSA_HALF_BITS)
    q_candidate |= (1 << (RSA_HALF_BITS - 1)) | 1
    q = _next_prime(q_candidate)

    return (p * q, PUBLIC_EXPONENT)
