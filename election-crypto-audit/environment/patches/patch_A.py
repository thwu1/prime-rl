"""
Remediation A: CSPRNG-Based Independent Key Generation

Replaces pool-based batch generation with per-key generation using
os.urandom() as the entropy source for each prime independently.
"""
import os
from election_system import _next_prime

RSA_HALF_BITS = 512
PUBLIC_EXPONENT = 65537


def generate_key():
    """Generate an RSA key pair using independent CSPRNG entropy for each prime."""
    p_entropy = os.urandom(64)
    p_candidate = int.from_bytes(p_entropy, 'big') >> (512 - RSA_HALF_BITS)
    p_candidate |= (1 << (RSA_HALF_BITS - 1)) | 1
    p = _next_prime(p_candidate)

    q_entropy = os.urandom(64)
    q_candidate = int.from_bytes(q_entropy, 'big') >> (512 - RSA_HALF_BITS)
    q_candidate |= (1 << (RSA_HALF_BITS - 1)) | 1
    q = _next_prime(q_candidate)

    return (p * q, PUBLIC_EXPONENT)
