"""
Sub-linear summatory function calculator.

Uses a smallest-prime-factor sieve for values up to N^{2/3}, then
memoized recursive identities with floor-division grouping for larger values.
Total complexity: O(N^{2/3}) time and O(N^{1/2}) memo space.
"""

import math
from array import array

MOD = 998244353
INV2 = pow(2, MOD - 2, MOD)  # modular inverse of 2


class _SummatoryEngine:
    """Precomputes sieve data and caches summatory function values."""

    def __init__(self, N):
        self.N = N
        V = max(int(round(N ** (2 / 3))) + 100, 1000)
        self.V = V

        # Smallest prime factor sieve
        spf = array("l", range(V + 1))
        for i in range(2, int(math.isqrt(V)) + 1):
            if spf[i] == i:
                for j in range(i * i, V + 1, i):
                    if spf[j] == j:
                        spf[j] = i

        # Compute multiplicative functions using SPF
        mu_a = array("l", [0] * (V + 1))
        phi_a = array("l", [0] * (V + 1))
        lam_a = array("l", [0] * (V + 1))
        mu_a[1] = phi_a[1] = lam_a[1] = 1

        for n in range(2, V + 1):
            p = spf[n]
            m = n // p
            if m % p == 0:
                mu_a[n] = 0
                phi_a[n] = phi_a[m] * p
            else:
                mu_a[n] = -mu_a[m]
                phi_a[n] = phi_a[m] * (p - 1)
            lam_a[n] = -lam_a[m]

        # Prefix sums over the sieve range
        self._M = array("l", [0] * (V + 1))
        self._P = array("l", [0] * (V + 1))
        self._L = array("l", [0] * (V + 1))
        for i in range(1, V + 1):
            self._M[i] = self._M[i - 1] + mu_a[i]
            self._P[i] = (self._P[i - 1] + phi_a[i]) % MOD
            self._L[i] = self._L[i - 1] + lam_a[i]

        # Memoization for values above the sieve range
        self._memo_M = {}
        self._memo_P = {}
        self._memo_L = {}

    def mertens(self, n):
        """M(n) = 1 - sum_{d=2}^{n} M(floor(n/d))"""
        if n <= self.V:
            return self._M[n]
        if n in self._memo_M:
            return self._memo_M[n]
        result = 1
        d = 2
        while d <= n:
            q = n // d
            d_next = n // q + 1
            result -= (d_next - d) * self.mertens(q)
            d = d_next
        self._memo_M[n] = result
        return result

    def totient_sum(self, n):
        """Phi(n) = n(n+1)/2 - sum_{d=2}^{n} Phi(floor(n/d))  (mod p)"""
        if n <= self.V:
            return self._P[n]
        if n in self._memo_P:
            return self._memo_P[n]
        nm = n % MOD
        result = nm * ((nm + 1) % MOD) % MOD * INV2 % MOD
        d = 2
        while d <= n:
            q = n // d
            d_next = n // q + 1
            result = (result - (d_next - d) % MOD * self.totient_sum(q)) % MOD
            d = d_next
        self._memo_P[n] = result
        return result

    def liouville_sum(self, n):
        """L(n) = isqrt(n) - sum_{d=2}^{n} L(floor(n/d))"""
        if n <= self.V:
            return self._L[n]
        if n in self._memo_L:
            return self._memo_L[n]
        result = int(math.isqrt(n))
        d = 2
        while d <= n:
            q = n // d
            d_next = n // q + 1
            result -= (d_next - d) * self.liouville_sum(q)
            d = d_next
        self._memo_L[n] = result
        return result


_engine = None
_engine_N = 0


def _get_engine(n):
    global _engine, _engine_N
    if _engine is None or n > _engine_N:
        _engine_N = n
        _engine = _SummatoryEngine(n)
    return _engine


def mertens(n: int) -> int:
    """Compute M(n) = sum of mu(k) for k = 1..n. Return exact integer."""
    if n <= 0:
        return 0
    return _get_engine(n).mertens(n)


def totient_sum(n: int) -> int:
    """Compute sum of phi(k) for k = 1..n, modulo 998244353."""
    if n <= 0:
        return 0
    return _get_engine(n).totient_sum(n)


def liouville_sum(n: int) -> int:
    """Compute L(n) = sum of lambda(k) for k = 1..n. Return exact integer."""
    if n <= 0:
        return 0
    return _get_engine(n).liouville_sum(n)
