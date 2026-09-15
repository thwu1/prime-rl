
import sys
import math
import time

sys.path.insert(0, "/app")

MOD = 998244353


def _sieve(limit):
    """Compute mu, phi, lambda for 1..limit using smallest-prime-factor sieve."""
    spf = list(range(limit + 1))
    for i in range(2, int(math.isqrt(limit)) + 1):
        if spf[i] == i:
            for j in range(i * i, limit + 1, i):
                if spf[j] == j:
                    spf[j] = i
    mu = [0] * (limit + 1)
    phi = [0] * (limit + 1)
    lam = [0] * (limit + 1)
    mu[1] = phi[1] = lam[1] = 1
    for n in range(2, limit + 1):
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


# Precompute reference data for small-value tests
_LIMIT = 1000
_mu, _phi, _lam = _sieve(_LIMIT)
_M = [0] * (_LIMIT + 1)
_P = [0] * (_LIMIT + 1)
_L = [0] * (_LIMIT + 1)
for _i in range(1, _LIMIT + 1):
    _M[_i] = _M[_i - 1] + _mu[_i]
    _P[_i] = (_P[_i - 1] + _phi[_i]) % MOD
    _L[_i] = _L[_i - 1] + _lam[_i]

import compute


def test_mertens_small():
    """Verify mertens(n) against brute force for small n."""
    for n in [1, 2, 3, 5, 10, 50, 100, 500, 1000]:
        got = compute.mertens(n)
        assert got == _M[n], f"mertens({n}): got {got}, expected {_M[n]}"


def test_totient_small():
    """Verify totient_sum(n) against brute force for small n."""
    for n in [1, 2, 3, 5, 10, 50, 100, 500, 1000]:
        got = compute.totient_sum(n)
        assert got == _P[n], f"totient_sum({n}): got {got}, expected {_P[n]}"


def test_liouville_small():
    """Verify liouville_sum(n) against brute force for small n."""
    for n in [1, 2, 3, 5, 10, 50, 100, 500, 1000]:
        got = compute.liouville_sum(n)
        assert got == _L[n], f"liouville_sum({n}): got {got}, expected {_L[n]}"


def test_medium_values():
    """Verify all three functions for n = 10^5 against brute force."""
    N = 100_000
    mu, phi, lam = _sieve(N)
    M_ref = sum(mu[1 : N + 1])
    P_ref = sum(phi[1 : N + 1]) % MOD
    L_ref = sum(lam[1 : N + 1])
    assert compute.mertens(N) == M_ref, (
        f"mertens({N}): got {compute.mertens(N)}, expected {M_ref}"
    )
    assert compute.totient_sum(N) == P_ref, (
        f"totient_sum({N}): got {compute.totient_sum(N)}, expected {P_ref}"
    )
    assert compute.liouville_sum(N) == L_ref, (
        f"liouville_sum({N}): got {compute.liouville_sum(N)}, expected {L_ref}"
    )


def test_performance():
    """All three functions for n = 10^10 must complete within 120 seconds."""
    N = 10**10
    start = time.time()
    m = compute.mertens(N)
    t = compute.totient_sum(N)
    el = compute.liouville_sum(N)
    elapsed = time.time() - start
    assert elapsed < 120, f"Took {elapsed:.1f}s, must be under 120s"
    assert isinstance(m, int), "mertens must return int"
    assert isinstance(t, int), "totient_sum must return int"
    assert isinstance(el, int), "liouville_sum must return int"
    # Sanity bounds: these summatory functions grow sub-linearly
    assert abs(m) < 10**6, f"|M(10^10)| = {abs(m)} seems unreasonably large"
    assert abs(el) < 10**6, f"|L(10^10)| = {abs(el)} seems unreasonably large"
    assert 0 <= t < MOD, f"totient_sum should be in [0, {MOD})"


def test_mertens_identity():
    """Cross-check: sum_{d=1}^{N} M(floor(N/d)) must equal 1."""
    N = 10**10
    total = 0
    d = 1
    while d <= N:
        q = N // d
        d_next = N // q + 1
        total += (d_next - d) * compute.mertens(q)
        d = d_next
    assert total == 1, f"Mertens identity failed: sum = {total}, expected 1"


def test_totient_identity():
    """Cross-check: sum_{d=1}^{N} Phi(floor(N/d)) must equal N(N+1)/2 mod p."""
    N = 10**10
    inv2 = pow(2, MOD - 2, MOD)
    expected = (N % MOD) * ((N + 1) % MOD) % MOD * inv2 % MOD
    total = 0
    d = 1
    while d <= N:
        q = N // d
        d_next = N // q + 1
        total = (total + (d_next - d) % MOD * compute.totient_sum(q)) % MOD
        d = d_next
    assert total == expected, (
        f"Totient identity failed: sum = {total}, expected {expected}"
    )


def test_liouville_mertens_cross():
    """Cross-check: L(N) must equal sum_{d=1}^{isqrt(N)} M(floor(N/d^2))."""
    N = 10**10
    L_val = compute.liouville_sum(N)
    cross = 0
    d = 1
    while d * d <= N:
        cross += compute.mertens(N // (d * d))
        d += 1
    assert L_val == cross, (
        f"Cross-check failed: L({N}) = {L_val}, sum M(N/d^2) = {cross}"
    )
