"""
Secure Vault - Cryptographic Utilities

This module contains the cryptographic primitives used by the vault system.
The vault uses a hybrid RSA+AES encryption scheme:
  1. An RSA key pair is generated for key encapsulation
  2. A random AES-128 key encrypts the vault contents (AES-CTR mode)
  3. The AES key is encrypted with the RSA public key (textbook RSA)

All random material is generated using Python's `random` module, seeded
with a master secret during vault initialization.

During initialization, the PRNG performs a calibration phase where 624
diagnostic outputs (each from getrandbits(32)) are logged for system
health monitoring. These outputs are obfuscated before being written
to the diagnostic log.
"""


def is_probable_prime(n):
    """
    Deterministic Miller-Rabin primality test using the first 20 prime witnesses.
    Used during RSA key generation to validate prime candidates.
    """
    if n < 2:
        return False
    small_primes = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47]
    if n in small_primes:
        return True
    if any(n % p == 0 for p in small_primes):
        return False

    # Write n-1 as 2^r * d
    r, d = 0, n - 1
    while d % 2 == 0:
        r += 1
        d //= 2

    witnesses = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47,
                 53, 59, 61, 67, 71]
    for a in witnesses:
        if a >= n:
            continue
        x = pow(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def obfuscate_calibration(value, index):
    """
    Obfuscate a 32-bit PRNG calibration output for the diagnostic log.

    Applies a reversible transformation:
      1. Circular left rotation by (index mod 32) bits (32-bit word)
      2. XOR with a deterministic mask: (0x6c078965 * (index + 1)) mod 2^32

    The mask constant 0x6c078965 is the Mersenne Twister state
    initialization multiplier from Knuth's TAOCP.
    """
    value &= 0xffffffff
    shift = index % 32
    if shift == 0:
        rotated = value
    else:
        rotated = ((value << shift) | (value >> (32 - shift))) & 0xffffffff
    mask = (0x6c078965 * (index + 1)) & 0xffffffff
    return rotated ^ mask


def generate_prime(rng, bits):
    """
    Generate a prime number of the specified bit length using the given PRNG.

    Process:
      1. Call rng.getrandbits(bits) to get a random candidate
      2. Set MSB (ensure exact bit length) and LSB (ensure odd)
      3. Test with is_probable_prime()
      4. Repeat until a prime is found
    """
    while True:
        candidate = rng.getrandbits(bits)
        candidate |= (1 << (bits - 1))
        candidate |= 1
        if is_probable_prime(candidate):
            return candidate
