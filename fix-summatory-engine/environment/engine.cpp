// Number Theory Summation Engine
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

// Integer square root
i64 isqrt(i64 N) {
    if (N <= 0) return 0;
    i64 r = (i64)sqrtl((long double)N);
    while (r > 0 && r * r > N) r--;
    while ((r + 1) * (r + 1) <= N) r++;
    return r;
}

// Sieve smallest prime factor up to L
std::vector<int> sieve_spf(int L) {
    std::vector<int> spf(L + 1, 0);
    for (int i = 2; i <= L; i++) {
        if (spf[i] == 0)
            for (int j = i; j <= L; j += i)
                if (spf[j] == 0) spf[j] = i;
    }
    return spf;
}

// Sieve Mobius function
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

// Sieve Euler's totient
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

// Divisor-vector: stores values for all distinct floor(N/k), k=1..N
// These take O(sqrt(N)) distinct values, stored in a flat array.
// Index mapping: for v <= sqrt(N), index = v; for v > sqrt(N), index = sz - floor(N/v).
struct DV {
    i64 N, rt;
    int sz;  // valid bucket indices: 1 to sz-1

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

// ============================================================
// Prime counting function pi(N) via the Lucy_Hedgehog DP
// ============================================================
i64 prime_count(i64 N) {
    if (N < 2) return 0;
    DV dv(N);
    std::vector<i64> S(dv.sz + 1);

    // S(v) starts as count of integers in [2, v]
    for (int i = 1; i < dv.sz; i++)
        S[i] = dv.val(i) - 1;

    // Sieve: for each prime p, subtract composites with smallest factor p
    for (i64 p = 2; p <= dv.rt; p++) {
        if (S[(int)p] == S[(int)(p - 1)]) continue;  // p is not prime
        i64 pcnt = S[(int)(p - 1)];  // pi(p-1)
        i64 p2 = p * p;

        for (int i = 1; i < dv.sz; i++) {
            i64 v = dv.val(i);
            if (v < p2) continue;
            S[i] -= S[dv.idx(v / p)] - pcnt;
        }
    }
    return S[dv.idx(N)];
}

// ============================================================
// Mertens function M(N) = sum_{k=1}^{N} mu(k)
// Uses identity: M(v) = 1 - sum_{d=2}^{v} M(floor(v/d))
// ============================================================
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

        i64 res = 0;
        i64 vrt = isqrt(v);

        // Part 1: large floor(v/d) values, enumerate d individually
        for (i64 d = 2; d <= v / (vrt + 1); d++)
            res -= M[dv.idx(v / d)];

        // Part 2: small floor(v/d) = g values, group d by value of floor(v/d)
        for (i64 g = vrt; g >= 1; g--) {
            i64 cnt = v / g - v / (g + 1);
            res -= M[(int)g] * cnt;
        }
        M[i] = res;
    }
    return M[dv.idx(N)];
}

// ============================================================
// Euler totient sum: S_phi(N) = sum_{k=1}^{N} phi(k)
// Uses identity: S_phi(v) = v*(v+1)/2 - sum_{d=2}^{v} S_phi(floor(v/d))
// ============================================================
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

        i64 res = v * v / 2;
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

// ============================================================
// Squarefree counting function Q(N) = sum_{k=1}^{N} |mu(k)|
// Uses identity: Q(N) = sum_{d=1}^{sqrt(N)} mu(d) * floor(N/d^2)
// ============================================================
i64 squarefree_count(i64 N) {
    if (N <= 0) return 0;
    i64 rt = isqrt(N);
    auto mu = sieve_mu((int)rt + 1);
    i64 res = 0;
    for (i64 d = 1; d <= rt; d++)
        res += mu[(int)d] * (N / (d * d));
    return res;
}

// ============================================================
// Liouville summatory function L(N) = sum_{k=1}^{N} lambda(k)
// where lambda(k) = (-1)^Omega(k), Omega = number of prime factors with multiplicity
// Use the relationship between L(N) and M(N) (Mertens function).
// ============================================================
i64 liouville_sum(i64 N) {
    // TODO: implement this function
    (void)N;
    return -999;
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
