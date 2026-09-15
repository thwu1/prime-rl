/* Number Theoretic Transform -- C backend for polynomial multiplication.
 *
 */
#include "ntt.h"
#include <stdlib.h>
#include <string.h>

long long power_mod(long long base, long long exp, long long mod) {
    long long result = 1;
    base %= mod;
    if (base < 0) base += mod;
    while (exp > 0) {
        if (exp & 1) result = result * base % mod;
        exp >>= 1;
        base = base * base % mod;
    }
    return result;
}

long long modinv_c(long long a) {
    return power_mod(a, MOD - 2, MOD);
}

void ntt(long long *a, int n, int invert) {
    int i, j, k, len;

    for (i = 1, j = 0; i < n; i++) {
        int bit = n >> 1;
        for (; j & bit; bit >>= 1)
            j ^= bit;
        j ^= bit;
        if (i < j) {
            long long tmp = a[i];
            a[i] = a[j];
            a[j] = tmp;
        }
    }

    for (len = 2; len <= n; len <<= 1) {
        long long w;
        if (invert)
            w = power_mod(PRIM_ROOT, MOD - 1 - (MOD - 1) / len, MOD);
        else
            w = power_mod(PRIM_ROOT, (MOD - 1) / len, MOD);

        for (i = 0; i < n; i += len) {
            long long wn = 1;
            for (k = 0; k < len / 2; k++) {
                long long u = a[i + k];
                long long v = a[i + k + len / 2] * wn % MOD;
                a[i + k] = (u + v) % MOD;
                a[i + k + len / 2] = (u - v) % MOD;
                wn = wn * w % MOD;
            }
        }
    }
}

long long* poly_multiply(long long *a, int na, long long *b, int nb, int *result_len) {
    int n = 1;
    *result_len = na + nb - 1;
    while (n < *result_len)
        n <<= 1;

    long long *fa = (long long *)calloc(n, sizeof(long long));
    long long *fb = (long long *)calloc(n, sizeof(long long));
    memcpy(fa, a, na * sizeof(long long));
    memcpy(fb, b, nb * sizeof(long long));

    ntt(fa, n, 0);
    ntt(fb, n, 0);

    {
        int i;
        for (i = 0; i < n; i++)
            fa[i] = fa[i] * fb[i] % MOD;
    }

    ntt(fa, n, 1);

    free(fb);
    return fa;
}

void free_poly(long long *p) {
    if (p) free(p);
}
