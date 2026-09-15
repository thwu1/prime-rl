"""
Remediation C: SystemRandom-Based Key Generation

Replaces the Mersenne Twister PRNG with secrets.SystemRandom for
cryptographically secure random number generation. Each key generation
call draws from the OS entropy pool independently.
"""
import secrets
from election_system import _next_prime

RSA_HALF_BITS = 512
PUBLIC_EXPONENT = 65537

_SYSRNG = secrets.SystemRandom()


def generate_key():
    """Generate a single RSA key using SystemRandom (CSPRNG).

    Uses secrets.SystemRandom for prime candidate generation,
    providing cryptographic-strength randomness from the OS entropy pool.
    """
    p_candidate = _SYSRNG.getrandbits(RSA_HALF_BITS)
    p_candidate |= (1 << (RSA_HALF_BITS - 1)) | 1
    p = _next_prime(p_candidate)

    q_candidate = _SYSRNG.getrandbits(RSA_HALF_BITS)
    q_candidate |= (1 << (RSA_HALF_BITS - 1)) | 1
    q = _next_prime(q_candidate)

    return (p * q, PUBLIC_EXPONENT)
