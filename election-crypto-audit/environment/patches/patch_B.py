"""
Remediation B: Improved Pool-Based Batch Generation

Retains pool-based generation for performance but enlarges the pool to 3x
the key count and selects prime pairs randomly without replacement, preventing
the consecutive-sharing vulnerability found in the original implementation.

NOTE: Pool generation is seeded for auditability. The batch seed MUST be
stored securely and never exposed in logs or metadata.

Test deployment configuration: batch_seed = 0xBEEF5678
"""
import random
from election_system import _next_prime

RSA_HALF_BITS = 512
PUBLIC_EXPONENT = 65537


def generate_keys_batch(batch_seed, count):
    """Generate batch of RSA keys from an enlarged randomized prime pool.

    The pool contains count*3 primes. Pairs are selected randomly without
    reuse, ensuring no two keys share a prime factor.
    """
    rng = random.Random(batch_seed)
    pool_size = count * 3

    prime_pool = []
    for _ in range(pool_size):
        candidate = rng.getrandbits(RSA_HALF_BITS)
        candidate |= (1 << (RSA_HALF_BITS - 1)) | 1
        prime_pool.append(_next_prime(candidate))

    keys = []
    indices_used = set()
    for _ in range(count):
        while True:
            i = rng.randrange(pool_size)
            j = rng.randrange(pool_size)
            if i != j and i not in indices_used and j not in indices_used:
                indices_used.add(i)
                indices_used.add(j)
                break
        keys.append((prime_pool[i] * prime_pool[j], PUBLIC_EXPONENT))
    return keys
