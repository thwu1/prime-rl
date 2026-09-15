#!/usr/bin/env python3
"""
Polynomial cube root over Z/PZ.

Given f(x) with f(0)=1 and N=65536 coefficients mod P=998244353,
compute g(x) such that g(x)^3 = f(x) mod (x^N, P).

Algorithm
---------
1. NTT (Number Theoretic Transform) for O(N log N) polynomial multiplication
   using primitive root 3 of P = 998244353 = 119 * 2^23 + 1.
2. Polynomial inverse via Newton's iteration:
   h_{k+1} = h_k * (2 - f * h_k)  mod x^{2^{k+1}}
3. Polynomial cube root via Newton's iteration on phi(g) = g^3 - f:
   g_{k+1} = (2*g_k + f * inv(g_k^2)) / 3  mod x^{2^{k+1}}
"""

import os


def main():
    with open('/app/data/params.txt') as pf:
        N = int(pf.readline())
        P = int(pf.readline())

    with open('/app/data/polynomial.txt') as pf:
        f_coeffs = [int(pf.readline()) for _ in range(N)]

    G = 3  # primitive root of P

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

    def poly_mul(a, b, trunc=None):
        la, lb = len(a), len(b)
        if trunc is None:
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

    def poly_inv(f_in, m):
        """Compute f_in^{-1} mod x^m via Newton's iteration."""
        h = [pow(f_in[0], P - 2, P)]
        cur = 1
        while cur < m:
            cur <<= 1
            fl = min(len(f_in), cur)
            ft = list(f_in[:fl]) + [0] * (cur - fl)
            fh = poly_mul(ft, h, cur)
            # Compute 2 - f*h
            neg_fh = [(P - fh[i]) % P for i in range(cur)]
            neg_fh[0] = (neg_fh[0] + 2) % P
            h = poly_mul(h, neg_fh, cur)
        return h[:m]

    def poly_cbrt(f_in, m):
        """Compute g with g^3 = f_in mod x^m, where f_in[0] = 1.

        Newton's method for phi(g) = g^3 - f = 0:
          g_{new} = g - phi(g)/phi'(g)
                  = g - (g^3 - f) / (3 g^2)
                  = (2g + f * g^{-2}) / 3
        """
        inv3 = pow(3, P - 2, P)
        g = [1]
        cur = 1
        while cur < m:
            cur <<= 1
            fl = min(len(f_in), cur)
            ft = list(f_in[:fl]) + [0] * (cur - fl)
            gp = list(g) + [0] * (cur - len(g))

            g_sq = poly_mul(gp, gp, cur)
            g_sq_inv = poly_inv(g_sq, cur)
            fg = poly_mul(ft, g_sq_inv, cur)

            g = [(2 * gp[i] + fg[i]) % P * inv3 % P for i in range(cur)]
        return g[:m]

    result = poly_cbrt(f_coeffs, N)

    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/result.txt', 'w') as out:
        for c in result:
            out.write(f'{c}\n')


if __name__ == '__main__':
    main()
