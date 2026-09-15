"""Modular arithmetic utilities for Z/998244353Z.

"""

MOD = 998244353


def power(base, exp, mod=MOD):
    """Compute base^exp mod mod using binary exponentiation."""
    result = 1
    base %= mod
    while exp > 0:
        if exp & 1:
            result = result * base % mod
        exp >>= 1
        base = base * base % mod
    return result


def modinv(a, mod=MOD):
    """Compute modular inverse of a mod mod using Fermat's little theorem.
    Requires mod to be prime and gcd(a, mod) = 1.
    """
    return power(a, mod - 2, mod)
