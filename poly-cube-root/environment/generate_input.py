#!/usr/bin/env python3
"""Generate deterministic input polynomial for the cube root task.

Strategy: generate a random polynomial g_orig of degree D-1 < N/3 with g_orig[0]=1,
then compute f = g_orig^3 exactly. Since deg(g_orig^3) = 3*(D-1) < N, f is a true
polynomial of degree < N, and its unique cube root mod (x^N, P) is g_orig.
This ensures the Schwartz-Zippel verification (point evaluation) is exact.
"""
import os
import random

random.seed(42)
N = 65536
P = 998244353
G = 3  # primitive root of P

D = N // 3 + 1  # 21846 coefficients for g_orig; 3*(D-1) = 65535 < N


def ntt(a, invert=False):
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
    ln = 2
    while ln <= n:
        if invert:
            w = pow(G, P - 1 - (P - 1) // ln, P)
        else:
            w = pow(G, (P - 1) // ln, P)
        half = ln >> 1
        for i in range(0, n, ln):
            wn = 1
            for k in range(half):
                u = a[i + k]
                v = a[i + k + half] * wn % P
                a[i + k] = (u + v) % P
                a[i + k + half] = (u - v) % P
                wn = wn * w % P
        ln <<= 1
    if invert:
        inv_n = pow(n, P - 2, P)
        for i in range(n):
            a[i] = a[i] * inv_n % P


def poly_mul(a, b):
    la, lb = len(a), len(b)
    trunc = la + lb - 1
    n = 1
    while n < la + lb:
        n <<= 1
    fa = list(a) + [0] * (n - la)
    fb = list(b) + [0] * (n - lb)
    ntt(fa)
    ntt(fb)
    for i in range(n):
        fa[i] = fa[i] * fb[i] % P
    ntt(fa, True)
    return fa[:trunc]


# Generate random g_orig: constant term 1, rest random in [1, P-1]
g_orig = [1] + [random.randint(1, P - 1) for _ in range(D - 1)]

# f = g_orig^3 (exact, no truncation; degree = 3*(D-1) = 65535, so 65536 coefficients)
g_sq = poly_mul(g_orig, g_orig)
f = poly_mul(g_sq, g_orig)
assert len(f) == N, f"Expected {N} coefficients, got {len(f)}"
assert f[0] == 1, f"f(0) should be 1, got {f[0]}"

os.makedirs('/app/data', exist_ok=True)
os.makedirs('/app/output', exist_ok=True)

with open('/app/data/polynomial.txt', 'w') as fout:
    for c in f:
        fout.write(f'{c}\n')

with open('/app/data/params.txt', 'w') as fout:
    fout.write(f'{N}\n{P}\n')
