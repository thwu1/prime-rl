"""
Security Patch A: PRNG State Desynchronization

Mitigation strategy: After the calibration phase completes, advance the PRNG
state by a fixed number of positions before using it for cryptographic key
generation. This creates a gap between the observed calibration outputs and
the PRNG state used for key material, preventing direct state-to-key mapping.

Usage:
    After calibration logging, call desynchronize(rng) before generate_prime().

Integration point in vault initialization sequence:
    1. PRNG seeded with master secret
    2. Calibration: 624 x getrandbits(32) logged
    3. >>> desynchronize(rng)  <<<  [THIS PATCH]
    4. RSA key generation: generate_prime(rng, 512) x 2
    5. AES key/nonce generation
"""


DESYNC_ROUNDS = 1000


def desynchronize(rng):
    """
    Advance the PRNG state by consuming DESYNC_ROUNDS outputs.

    After this call, the PRNG's internal state will have been twisted
    multiple times, making the relationship between calibration outputs
    and subsequent key material non-trivial.
    """
    for _ in range(DESYNC_ROUNDS):
        rng.getrandbits(32)
    return rng


PATCH_INFO = {
    "name": "PRNG State Desynchronization",
    "version": "1.0",
    "author": "vault-security-team",
    "description": (
        "Advances PRNG state by 1000 positions between calibration and key "
        "generation to break synchronization between observed outputs and "
        "key material derivation."
    ),
}
