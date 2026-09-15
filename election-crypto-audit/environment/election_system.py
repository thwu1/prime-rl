"""
SecureVote Election Cryptosystem v2.3.1
RSA-based vote encryption for district-level elections.

This module provides the cryptographic primitives used by SecureVote,
including three key generation methods for different deployment scenarios
and a vote encoding scheme with HMAC-based identity binding.

AUDIT NOTICE: This system has been flagged for cryptographic review.
Auditors should examine all key generation paths for potential weaknesses.
"""

import hashlib
import hmac
import random

# ============================================================
# System Parameters
# ============================================================

RSA_KEY_BITS = 1024
RSA_HALF_BITS = RSA_KEY_BITS // 2
PUBLIC_EXPONENT = 65537
CANDIDATES = ["Aster", "Bloom", "Cedar", "Dahlia"]

# ============================================================
# Primality Testing (deterministic, fixed-witness Miller-Rabin)
# ============================================================

_SMALL_PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47,
                 53, 59, 61, 67, 71, 73, 79, 83, 89, 97]


def _miller_rabin(n, rounds=25):
    """Deterministic Miller-Rabin with first 25 small primes as witnesses."""
    if n < 2:
        return False
    if n in _SMALL_PRIMES:
        return True
    if any(n % p == 0 for p in _SMALL_PRIMES):
        return False

    r, d = 0, n - 1
    while d % 2 == 0:
        r += 1
        d //= 2

    for a in _SMALL_PRIMES[:rounds]:
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


def _next_prime(n):
    """Return the smallest prime >= n."""
    if n <= 2:
        return 2
    if n % 2 == 0:
        n += 1
    while not _miller_rabin(n):
        n += 2
    return n


# ============================================================
# Key Generation Methods
# ============================================================

def generate_key_batch(batch_seed, count):
    """
    Batch key generation using a shared prime pool.

    Optimized for high-throughput enrollment periods where many keys
    must be generated quickly from a single initialization seed.
    A prime pool is pre-computed and keys are assembled from
    consecutive pool entries for cache efficiency.

    Args:
        batch_seed: Integer seed for deterministic pool generation
        count: Number of key pairs to generate

    Returns:
        List of (n, e) tuples
    """
    rng = random.Random(batch_seed)

    pool_size = count + 1
    prime_pool = []
    for _ in range(pool_size):
        candidate = rng.getrandbits(RSA_HALF_BITS)
        candidate |= (1 << (RSA_HALF_BITS - 1)) | 1
        prime_pool.append(_next_prime(candidate))

    keys = []
    for i in range(count):
        p = prime_pool[i]
        q = prime_pool[i + 1]
        n = p * q
        keys.append((n, PUBLIC_EXPONENT))
    return keys


def generate_key_seeded(timestamp):
    """
    Timestamp-seeded key generation for field deployment.

    Designed for environments with limited entropy sources where
    hardware RNG may not be available. Uses Python's Mersenne Twister
    PRNG seeded with the deployment timestamp for reproducibility.

    Args:
        timestamp: Unix timestamp (integer) for seed derivation

    Returns:
        (n, e) tuple
    """
    rng = random.Random(timestamp)

    p_bits = rng.getrandbits(RSA_HALF_BITS)
    p_bits |= (1 << (RSA_HALF_BITS - 1)) | 1
    p = _next_prime(p_bits)

    q_bits = rng.getrandbits(RSA_HALF_BITS)
    q_bits |= (1 << (RSA_HALF_BITS - 1)) | 1
    q = _next_prime(q_bits)

    return (p * q, PUBLIC_EXPONENT)


def generate_key_adjacent(seed_value):
    """
    Hash-derived key generation with deterministic prime derivation.

    Derives both primes from the seed value using SHA-512 for full
    auditability. Each prime is derived independently to ensure
    the key can be regenerated from the seed alone.

    Args:
        seed_value: Integer seed for prime derivation

    Returns:
        (n, e) tuple
    """
    # Derive p from seed
    p_material = hashlib.sha512(f"sv_prime_p:{seed_value}".encode()).digest()
    p_candidate = int.from_bytes(p_material, 'big') >> (512 - RSA_HALF_BITS)
    p_candidate |= (1 << (RSA_HALF_BITS - 1)) | 1
    p = _next_prime(p_candidate)

    # Derive q from related material
    q_material = hashlib.sha512(f"sv_prime_q:{seed_value}".encode()).digest()
    q_offset = int.from_bytes(q_material[:5], 'big')
    q_candidate = p + q_offset * 2 + 1
    if q_candidate % 2 == 0:
        q_candidate += 1
    q = _next_prime(q_candidate)

    return (p * q, PUBLIC_EXPONENT)


# ============================================================
# Vote Encoding
# ============================================================

def encode_vote(voter_id, candidate_index):
    """
    Encode a vote as an integer suitable for RSA encryption.
    Binds the vote to the voter's identity using HMAC-SHA256 padding.

    Format: HMAC-SHA256(key=voter_id, msg="securevote_ballot_v2") || candidate_index (1 byte)

    Args:
        voter_id: String voter identifier (e.g. "V001")
        candidate_index: Zero-based index into the CANDIDATES list

    Returns:
        Integer plaintext for RSA encryption
    """
    tag = hmac.new(
        voter_id.encode(),
        b"securevote_ballot_v2",
        hashlib.sha256
    ).digest()
    msg_bytes = tag + bytes([candidate_index])
    return int.from_bytes(msg_bytes, 'big')


def encrypt_vote(plaintext, n, e):
    """Standard textbook RSA encryption: c = m^e mod n"""
    assert 0 < plaintext < n, "Plaintext out of range for this modulus"
    return pow(plaintext, e, n)
