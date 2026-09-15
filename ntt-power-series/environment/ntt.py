"""Number Theoretic Transform for polynomial multiplication in Z/998244353Z.

"""

from mod_arith import MOD, power, modinv

PRIMITIVE_ROOT = 3


def ntt(a, invert=False):
    """Compute the Number Theoretic Transform of array a (in-place).

    If invert=True, compute the inverse NTT.
    The transform operates modulo MOD = 998244353 = 119 * 2^23 + 1,
    which supports NTT for arrays of length up to 2^23.
    """
    n = len(a)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            a[i], a[j] = a[j], a[i]

    length = 2
    while length <= n:
        if invert:
            w = power(PRIMITIVE_ROOT, MOD - 1 - (MOD - 1) // length)
        else:
            w = power(PRIMITIVE_ROOT, (MOD - 1) // length)

        for i in range(0, n, length):
            wn = 1
            for k in range(length // 2):
                u = a[i + k]
                v = a[i + k + length // 2] * wn % MOD
                a[i + k] = (u + v) % MOD
                a[i + k + length // 2] = (u - v + MOD) % MOD
                wn = wn * w % MOD
        length <<= 1

    return a


def multiply(a, b):
    """Multiply two polynomials using NTT.

    Returns the coefficient list of the product polynomial.
    """
    result_len = len(a) + len(b) - 1
    n = 1
    while n < result_len:
        n <<= 1
    fa = list(a) + [0] * (n - len(a))
    fb = list(b) + [0] * (n - len(b))
    ntt(fa)
    ntt(fb)
    for i in range(n):
        fa[i] = fa[i] * fb[i] % MOD
    ntt(fa, invert=True)
    return fa[:result_len]
