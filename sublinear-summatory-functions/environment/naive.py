"""
Naive O(N) reference implementation of summatory functions.
Correct for small inputs but infeasible for N > ~10^6 (memory and time).

Usage:
    python3 naive.py <function> <n>
    e.g.:  python3 naive.py mertens 1000
"""

import sys
import math

MOD = 998244353


def sieve(N):
    """Compute mu, phi, lambda for k = 1..N using smallest-prime-factor sieve."""
    spf = list(range(N + 1))
    for i in range(2, int(math.isqrt(N)) + 1):
        if spf[i] == i:
            for j in range(i * i, N + 1, i):
                if spf[j] == j:
                    spf[j] = i

    mu = [0] * (N + 1)
    phi = [0] * (N + 1)
    lam = [0] * (N + 1)
    mu[1] = phi[1] = lam[1] = 1

    for n in range(2, N + 1):
        p = spf[n]
        m = n // p
        if m % p == 0:
            mu[n] = 0
            phi[n] = phi[m] * p
        else:
            mu[n] = -mu[m]
            phi[n] = phi[m] * (p - 1)
        lam[n] = -lam[m]

    return mu, phi, lam


def mertens(N):
    """M(N) = sum of mu(k) for k = 1..N."""
    mu, _, _ = sieve(N)
    return sum(mu[1 : N + 1])


def totient_sum(N):
    """Phi(N) = sum of phi(k) for k = 1..N, modulo 998244353."""
    _, phi, _ = sieve(N)
    return sum(phi[1 : N + 1]) % MOD


def liouville_sum(N):
    """L(N) = sum of lambda(k) for k = 1..N."""
    _, _, lam = sieve(N)
    return sum(lam[1 : N + 1])


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <mertens|totient_sum|liouville_sum> <n>")
        sys.exit(1)

    func_name = sys.argv[1]
    n = int(sys.argv[2])

    if func_name == "mertens":
        print(mertens(n))
    elif func_name == "totient_sum":
        print(totient_sum(n))
    elif func_name == "liouville_sum":
        print(liouville_sum(n))
    else:
        print(f"Unknown function: {func_name}")
        sys.exit(1)
