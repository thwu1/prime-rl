#!/usr/bin/env python3
"""
Write the corrected engine.cpp to /app/engine.cpp.

Fixes applied:
1. Lucy DP: iterate in DESCENDING order (not ascending) to avoid using
   already-updated sub-results, analogous to 0-1 knapsack ordering.
2. Mertens recurrence base case: M(v) = 1 - sum, not 0 - sum.
3. Euler totient sum: use v*(v+1)/2 (triangular number), not v*v/2.
4. Implement liouville_sum using identity L(N) = sum_{d=1}^{sqrt(N)} M(floor(N/d^2))
   derived from the Dirichlet series relation zeta(2s)/zeta(s).
"""

CORRECTED_SOURCE = r'''// Number Theory Summation Engine (corrected)
// Computes: pi(N), M(N), phi_sum(N), Q(N), L(N)
// Uses sub-linear algorithms based on the hyperbola method / Dirichlet series approach
//

#include <cstdint>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <algorithm>

using i64 = int64_t;

i64 isqrt(i64 N) {
    if (N <= 0) return 0;
    i64 r = (i64)sqrtl((long double)N);
    while (r > 0 && r * r > N) r--;
    while ((r + 1) * (r + 1) <= N) r++;
    return r;
}

std::vector<int> sieve_spf(int L) {
    std::vector<int> spf(L + 1, 0);
    for (int i = 2; i <= L; i++) {
        if (spf[i] == 0)
            for (int j = i; j <= L; j += i)
                if (spf[j] == 0) spf[j] = i;
    }
    return spf;
}

std::vector<int> sieve_mu(int L) {
    auto spf = sieve_spf(L);
    std::vector<int> mu(L + 1, 0);
    mu[1] = 1;
    for (int i = 2; i <= L; i++) {
        int p = spf[i], q = i / p;
        mu[i] = (q % p == 0) ? 0 : -mu[q];
    }
    return mu;
}

std::vector<i64> sieve_phi(int L) {
    auto spf = sieve_spf(L);
    std::vector<i64> phi(L + 1, 0);
    phi[1] = 1;
    for (int i = 2; i <= L; i++) {
        int p = spf[i], q = i / p;
        phi[i] = (q % p == 0) ? phi[q] * p : phi[q] * (p - 1);
    }
    return phi;
}

struct DV {
    i64 N, rt;
    int sz;

    DV() : N(0), rt(0), sz(0) {}
    DV(i64 N_) : N(N_), rt(isqrt(N_)) {
        sz = (int)(2 * rt + (rt * (rt + 1) <= N ? 1 : 0));
    }

    int idx(i64 v) const {
        if (v <= rt) return (int)v;
        return sz - (int)(N / v);
    }

    i64 val(int i) const {
        if (i <= (int)rt) return i;
        return N / (sz - i);
    }
};

// FIX 1: Lucy DP iterates in DESCENDING order
i64 prime_count(i64 N) {
    if (N < 2) return 0;
    DV dv(N);
    std::vector<i64> S(dv.sz + 1);

    for (int i = 1; i < dv.sz; i++)
        S[i] = dv.val(i) - 1;

    for (i64 p = 2; p <= dv.rt; p++) {
        if (S[(int)p] == S[(int)(p - 1)]) continue;
        i64 pcnt = S[(int)(p - 1)];
        i64 p2 = p * p;

        for (int i = dv.sz - 1; i >= 1; i--) {
            i64 v = dv.val(i);
            if (v < p2) break;
            S[i] -= S[dv.idx(v / p)] - pcnt;
        }
    }
    return S[dv.idx(N)];
}

// FIX 2: Mertens base case is 1
i64 mertens(i64 N) {
    if (N <= 0) return 0;
    DV dv(N);
    int L = std::max((int)dv.rt + 10, 1000);
    auto mu = sieve_mu(L);
    std::vector<i64> mu_pref(L + 1, 0);
    for (int i = 1; i <= L; i++)
        mu_pref[i] = mu_pref[i - 1] + mu[i];

    std::vector<i64> M(dv.sz + 1, 0);
    for (int i = 1; i < dv.sz; i++) {
        i64 v = dv.val(i);
        if (v <= L) { M[i] = mu_pref[(int)v]; continue; }

        i64 res = 1;
        i64 vrt = isqrt(v);

        for (i64 d = 2; d <= v / (vrt + 1); d++)
            res -= M[dv.idx(v / d)];
        for (i64 g = vrt; g >= 1; g--) {
            i64 cnt = v / g - v / (g + 1);
            res -= M[(int)g] * cnt;
        }
        M[i] = res;
    }
    return M[dv.idx(N)];
}

// FIX 3: Totient uses v*(v+1)/2
i64 totient_sum(i64 N) {
    if (N <= 0) return 0;
    DV dv(N);
    int L = std::max((int)dv.rt + 10, 1000);
    auto phi = sieve_phi(L);
    std::vector<i64> phi_pref(L + 1, 0);
    for (int i = 1; i <= L; i++)
        phi_pref[i] = phi_pref[i - 1] + phi[i];

    std::vector<i64> Sp(dv.sz + 1, 0);
    for (int i = 1; i < dv.sz; i++) {
        i64 v = dv.val(i);
        if (v <= L) { Sp[i] = phi_pref[(int)v]; continue; }

        i64 res = v * (v + 1) / 2;
        i64 vrt = isqrt(v);

        for (i64 d = 2; d <= v / (vrt + 1); d++)
            res -= Sp[dv.idx(v / d)];
        for (i64 g = vrt; g >= 1; g--) {
            i64 cnt = v / g - v / (g + 1);
            res -= Sp[(int)g] * cnt;
        }
        Sp[i] = res;
    }
    return Sp[dv.idx(N)];
}

i64 squarefree_count(i64 N) {
    if (N <= 0) return 0;
    i64 rt = isqrt(N);
    auto mu = sieve_mu((int)rt + 1);
    i64 res = 0;
    for (i64 d = 1; d <= rt; d++)
        res += mu[(int)d] * (N / (d * d));
    return res;
}

// FIX 4: Implement Liouville summatory function
// Identity: L(N) = sum_{d=1}^{sqrt(N)} M(floor(N/d^2))
// Derived from: lambda = mu * 1_{squares} in Dirichlet convolution
// (equivalently, zeta(2s)/zeta(s) is the Dirichlet series for lambda)
i64 liouville_sum(i64 N) {
    if (N <= 0) return 0;

    // Compute M(v) for all v = floor(N/k)
    DV dv(N);
    int L = std::max((int)dv.rt + 10, 1000);
    auto mu = sieve_mu(L);
    std::vector<i64> mu_pref(L + 1, 0);
    for (int i = 1; i <= L; i++)
        mu_pref[i] = mu_pref[i - 1] + mu[i];

    std::vector<i64> M(dv.sz + 1, 0);
    for (int i = 1; i < dv.sz; i++) {
        i64 v = dv.val(i);
        if (v <= L) { M[i] = mu_pref[(int)v]; continue; }
        i64 res = 1;
        i64 vrt = isqrt(v);
        for (i64 d = 2; d <= v / (vrt + 1); d++)
            res -= M[dv.idx(v / d)];
        for (i64 g = vrt; g >= 1; g--)
            res -= M[(int)g] * (v / g - v / (g + 1));
        M[i] = res;
    }

    // L(N) = sum_{d=1}^{sqrt(N)} M(floor(N/d^2))
    i64 result = 0;
    for (i64 d = 1; d * d <= N; d++)
        result += M[dv.idx(N / (d * d))];
    return result;
}

int main(int argc, char** argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s N\n", argv[0]);
        return 1;
    }
    i64 N = atoll(argv[1]);
    if (N < 1) {
        fprintf(stderr, "N must be positive\n");
        return 1;
    }

    printf("pi %lld\n", (long long)prime_count(N));
    printf("M %lld\n", (long long)mertens(N));
    printf("phi_sum %lld\n", (long long)totient_sum(N));
    printf("Q %lld\n", (long long)squarefree_count(N));
    printf("L %lld\n", (long long)liouville_sum(N));

    return 0;
}
'''

with open('/app/engine.cpp', 'w') as f:
    f.write(CORRECTED_SOURCE)
