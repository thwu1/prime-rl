/*
 * Sub-linear summatory function computation using Dirichlet series identities.
 * Sieve up to V = N^{2/3}, then memoised recursive identities with
 * floor-division grouping for values above V.  O(N^{2/3}) total work.
 */

#include "dirichlet.h"
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define MOD 998244353LL

/* ------------------------------------------------------------------ */
/*  Sieve data (persists across calls, grows monotonically)           */
/* ------------------------------------------------------------------ */
static int64_t sieve_V = 0;
static int64_t *M_pre = NULL;   /* M_pre[i] = M(i) for i <= sieve_V */
static int64_t *P_pre = NULL;   /* P_pre[i] = Phi(i) mod p           */
static int64_t *L_pre = NULL;   /* L_pre[i] = L(i)                   */

/* ------------------------------------------------------------------ */
/*  Memo arrays — floor-division indexed                              */
/* ------------------------------------------------------------------ */
static int64_t memo_N  = 0;
static int64_t memo_rt = 0;
static int     memo_len = 0;

static int64_t *memo_M = NULL, *memo_P = NULL, *memo_L = NULL;
static int8_t  *set_M  = NULL, *set_P  = NULL, *set_L  = NULL;

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

static int64_t isqrt_safe(int64_t n) {
    if (n <= 0) return 0;
    int64_t r = (int64_t)sqrt((double)n);
    while (r > 0 && r * r > n) r--;
    while ((r + 1) * (r + 1) <= n) r++;
    return r;
}

/* Modular exponentiation (uses __int128 for intermediate products) */
static int64_t mod_pow(int64_t base, int64_t exp, int64_t m) {
    int64_t result = 1;
    base %= m;
    if (base < 0) base += m;
    while (exp > 0) {
        if (exp & 1) result = (__int128)result * base % m;
        exp >>= 1;
        base = (__int128)base * base % m;
    }
    return result;
}

/* Map a value v (which is always some floor(N/d)) to a memo index. */
static int get_idx(int64_t v) {
    if (v <= memo_rt) return (int)v;
    return memo_len - (int)(memo_N / v);
}

/* ------------------------------------------------------------------ */
/*  Sieve construction                                                */
/* ------------------------------------------------------------------ */

static void build_sieve(int64_t V) {
    if (sieve_V >= V) return;
    free(M_pre); free(P_pre); free(L_pre);
    sieve_V = V;

    int     *spf = (int     *)calloc(V + 1, sizeof(int));
    int8_t  *mu  = (int8_t  *)calloc(V + 1, sizeof(int8_t));
    int64_t *phi = (int64_t *)calloc(V + 1, sizeof(int64_t));
    int8_t  *lam = (int8_t  *)calloc(V + 1, sizeof(int8_t));

    for (int64_t i = 0; i <= V; i++) spf[i] = (int)i;
    for (int64_t i = 2; i * i <= V; i++) {
        if (spf[i] == (int)i) {
            for (int64_t j = i * i; j <= V; j += i)
                if (spf[j] == (int)j) spf[j] = (int)i;
        }
    }

    mu[1] = 1; phi[1] = 1; lam[1] = 1;
    for (int64_t n = 2; n <= V; n++) {
        int p = spf[n];
        int64_t m = n / p;
        if (m % p == 0) { mu[n] = 0;       phi[n] = phi[m] * p;       }
        else            { mu[n] = -mu[m];   phi[n] = phi[m] * (p - 1); }
        lam[n] = -lam[m];
    }

    M_pre = (int64_t *)calloc(V + 1, sizeof(int64_t));
    P_pre = (int64_t *)calloc(V + 1, sizeof(int64_t));
    L_pre = (int64_t *)calloc(V + 1, sizeof(int64_t));
    for (int64_t i = 1; i <= V; i++) {
        M_pre[i] = M_pre[i - 1] + mu[i];
        P_pre[i] = (P_pre[i - 1] + phi[i]) % MOD;
        L_pre[i] = L_pre[i - 1] + lam[i];
    }
    free(spf); free(mu); free(phi); free(lam);
}

/* ------------------------------------------------------------------ */
/*  Memo allocation                                                   */
/* ------------------------------------------------------------------ */

static void init_memo(int64_t N) {
    if (N <= memo_N) return;
    free(memo_M); free(memo_P); free(memo_L);
    free(set_M);  free(set_P);  free(set_L);
    memo_N  = N;
    memo_rt = isqrt_safe(N);
    memo_len = (int)(2 * memo_rt + (memo_rt * (memo_rt + 1) <= N));

    memo_M = (int64_t *)calloc(memo_len + 1, sizeof(int64_t));
    memo_P = (int64_t *)calloc(memo_len + 1, sizeof(int64_t));
    memo_L = (int64_t *)calloc(memo_len + 1, sizeof(int64_t));
    set_M  = (int8_t  *)calloc(memo_len + 1, sizeof(int8_t));
    set_P  = (int8_t  *)calloc(memo_len + 1, sizeof(int8_t));
    set_L  = (int8_t  *)calloc(memo_len + 1, sizeof(int8_t));
}

/* ------------------------------------------------------------------ */
/*  Recursive summatory functions                                     */
/* ------------------------------------------------------------------ */

/*  M(n) = 1 - sum_{d=2}^{n} M(floor(n/d))  */
static int64_t mertens_rec(int64_t n) {
    if (n <= sieve_V) return M_pre[n];
    int idx = get_idx(n);
    if (set_M[idx]) return memo_M[idx];

    int64_t result = 1;
    int64_t d = 2;
    while (d <= n) {
        int64_t q      = n / d;
        int64_t d_next = n / q + 1;
        result -= (d_next - d) * mertens_rec(q);
        d = d_next;
    }
    memo_M[idx] = result;
    set_M[idx]  = 1;
    return result;
}

/*  Phi(n) = n(n+1)/2 - sum_{d=2}^{n} Phi(floor(n/d))   (mod p)  */
static int64_t totient_rec(int64_t n) {
    if (n <= sieve_V) return P_pre[n];
    int idx = get_idx(n);
    if (set_P[idx]) return memo_P[idx];

    /* Compute n*(n+1)/2 mod MOD without overflow using __int128 and modular inverse */
    int64_t nm = n % MOD;
    int64_t inv2 = mod_pow(2, MOD - 2, MOD);
    int64_t result = (__int128)nm * ((n + 1) % MOD) % MOD * inv2 % MOD;

    int64_t d = 2;
    while (d <= n) {
        int64_t q      = n / d;
        int64_t d_next = n / q + 1;
        int64_t cnt    = (d_next - d) % MOD;
        result = ((result - cnt * totient_rec(q) % MOD) % MOD + MOD) % MOD;
        d = d_next;
    }
    memo_P[idx] = result;
    set_P[idx]  = 1;
    return result;
}

/*  L(n) = floor(sqrt(n)) - sum_{d=2}^{n} L(floor(n/d))  */
static int64_t liouville_rec(int64_t n) {
    if (n <= sieve_V) return L_pre[n];
    int idx = get_idx(n);
    if (set_L[idx]) return memo_L[idx];

    int64_t result = isqrt_safe(n);

    int64_t d = 2;
    while (d <= n) {
        int64_t q      = n / d;
        int64_t d_next = n / q + 1;
        result -= (d_next - d) * liouville_rec(q);
        d = d_next;
    }
    memo_L[idx] = result;
    set_L[idx]  = 1;
    return result;
}

/* ------------------------------------------------------------------ */
/*  Public API                                                        */
/* ------------------------------------------------------------------ */

int64_t mertens(int64_t n) {
    if (n <= 0) return 0;
    int64_t V = (int64_t)(pow((double)n, 2.0 / 3.0) + 200);
    if (V < 1000) V = 1000;
    build_sieve(V);
    init_memo(n);
    return mertens_rec(n);
}

int64_t totient_sum(int64_t n) {
    if (n <= 0) return 0;
    int64_t V = (int64_t)(pow((double)n, 2.0 / 3.0) + 200);
    if (V < 1000) V = 1000;
    build_sieve(V);
    init_memo(n);
    return totient_rec(n);
}

int64_t liouville_sum(int64_t n) {
    if (n <= 0) return 0;
    int64_t V = (int64_t)(pow((double)n, 2.0 / 3.0) + 200);
    if (V < 1000) V = 1000;
    build_sieve(V);
    init_memo(n);
    return liouville_rec(n);
}
