#ifndef NTT_H
#define NTT_H

#define MOD 998244353LL
#define PRIM_ROOT 3LL

long long power_mod(long long base, long long exp, long long mod);
long long modinv_c(long long a);
void ntt(long long *a, int n, int invert);
long long* poly_multiply(long long *a, int na, long long *b, int nb, int *result_len);
void free_poly(long long *p);

#endif
