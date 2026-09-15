"""
Security Patch B: CSPRNG Key Isolation

Mitigation strategy: Decouple cryptographic key generation from the diagnostic
PRNG entirely. All RSA key material and AES keys are generated using the
operating system's cryptographically secure random source (os.urandom backed
by /dev/urandom). The calibration phase continues to use the original MT19937
PRNG for backwards compatibility with the monitoring infrastructure.

Usage:
    Replace generate_prime(rng, 512) with generate_prime_secure(512).
    Replace rng.getrandbits(128) with generate_aes_key_secure().
    Replace rng.getrandbits(64) with generate_nonce_secure().

Integration point in vault initialization sequence:
    1. PRNG seeded with master secret
    2. Calibration: 624 x getrandbits(32) logged  [unchanged]
    3. RSA key generation: generate_prime_secure(512) x 2  [PATCHED]
    4. AES key: generate_aes_key_secure()                  [PATCHED]
    5. Nonce: generate_nonce_secure()                      [PATCHED]
"""

import os
import sys

sys.path.insert(0, "/app/vault")
from crypto_utils import is_probable_prime


def generate_prime_secure(bits):
    """
    Generate a prime of the specified bit length using os.urandom().
    Completely independent of any MT19937 PRNG instance.
    """
    while True:
        candidate_bytes = os.urandom(bits // 8)
        candidate = int.from_bytes(candidate_bytes, "big")
        candidate |= 1 << (bits - 1)  # Ensure exact bit length
        candidate |= 1  # Ensure odd
        if is_probable_prime(candidate):
            return candidate


def generate_aes_key_secure():
    """Generate a 128-bit AES key from os.urandom()."""
    return os.urandom(16)


def generate_nonce_secure():
    """Generate a 64-bit nonce from os.urandom()."""
    return os.urandom(8)


PATCH_INFO = {
    "name": "CSPRNG Key Isolation",
    "version": "1.0",
    "author": "vault-security-team",
    "description": (
        "Replaces MT19937 with os.urandom for all cryptographic key material. "
        "Calibration PRNG remains unchanged for monitoring compatibility."
    ),
}
