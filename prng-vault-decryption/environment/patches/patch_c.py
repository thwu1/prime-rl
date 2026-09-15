"""
Security Patch C: Seed Hardening via PBKDF2

Mitigation strategy: Strengthen the PRNG seed using PBKDF2 key derivation
before initializing MT19937. Instead of seeding the PRNG directly with the
master secret, derive a 512-bit high-entropy seed via PBKDF2-HMAC-SHA256
with 600,000 iterations and a fixed domain-separation salt. This prevents
dictionary attacks and brute-force seed recovery even when the master secret
has low entropy.

Usage:
    Replace rng = random.Random(master_secret)
    with    rng = create_hardened_rng(master_secret)

Integration point in vault initialization sequence:
    1. >>> rng = create_hardened_rng(master_secret) <<<  [THIS PATCH]
    2. Calibration: 624 x getrandbits(32) logged
    3. RSA key generation: generate_prime(rng, 512) x 2
    4. AES key/nonce generation
"""

import hashlib
import random


PBKDF2_ITERATIONS = 600_000
PBKDF2_SALT = b"vault-prng-seed-hardening-v1"
PBKDF2_DKLEN = 64  # 512-bit derived key


def create_hardened_rng(master_secret):
    """
    Create a Random instance seeded with PBKDF2-derived key material.

    Uses PBKDF2-HMAC-SHA256 with a domain-separation salt and 600k iterations
    to transform any master secret (even a weak passphrase) into a 512-bit
    high-entropy seed for MT19937. This makes offline brute-force of the
    original master secret computationally infeasible.
    """
    secret_bytes = str(master_secret).encode("utf-8")
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        secret_bytes,
        PBKDF2_SALT,
        PBKDF2_ITERATIONS,
        dklen=PBKDF2_DKLEN,
    )
    rng = random.Random()
    rng.seed(int.from_bytes(derived, "big"))
    return rng


PATCH_INFO = {
    "name": "Seed Hardening via PBKDF2",
    "version": "1.0",
    "author": "vault-security-team",
    "description": (
        "Hardens PRNG initialization by deriving the seed through PBKDF2 with "
        "600k iterations. Prevents brute-force seed recovery even with weak "
        "master secrets."
    ),
}
