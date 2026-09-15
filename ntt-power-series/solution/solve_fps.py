"""Corrected Formal Power Series operations.

Fixes poly_inv Newton step and implements poly_exp and poly_pow.

"""

from ntt_binding import multiply
from mod_arith import MOD, modinv, power


def poly_inv(f, n):
    """Compute the first n terms of 1/f(x) mod x^n.

    Newton's iteration: g_{k+1} = g_k * (2 - f * g_k) mod x^{2^{k+1}}
    The polynomial (2 - f*g) has 2 only in the constant term.
    """
    assert len(f) > 0 and f[0] != 0
    g = [modinv(f[0])]
    m = 1
    while m < n:
        m <<= 1
        f_trunc = (list(f[:m]) + [0] * m)[:m]
        fg = multiply(f_trunc, g)[:m]
        tmp = [(-fg[i]) % MOD for i in range(m)]
        tmp[0] = (tmp[0] + 2) % MOD
        g = multiply(g, tmp)[:m]
    return g[:n]


def poly_deriv(f):
    """Compute the formal derivative f'(x)."""
    n = len(f)
    if n <= 1:
        return [0]
    return [i * f[i] % MOD for i in range(1, n)]


def poly_integ(f):
    """Compute the formal integral of f (constant of integration = 0)."""
    n = len(f)
    result = [0] * (n + 1)
    for i in range(n):
        result[i + 1] = f[i] * modinv(i + 1) % MOD
    return result


def poly_ln(f, n):
    """Compute the first n terms of ln(f(x)) mod x^n.

    Uses: ln(f) = integral(f' / f)
    Precondition: f[0] = 1
    """
    assert len(f) > 0 and f[0] == 1
    f_padded = list(f) + [0] * max(0, n - len(f))
    df = poly_deriv(f_padded[:n])
    inv_f = poly_inv(f_padded, n)
    product = multiply(df, inv_f)[:n - 1]
    result = poly_integ(product)
    return result[:n]


def poly_sqrt(f, n):
    """Compute the first n terms of sqrt(f(x)) mod x^n.

    Newton's iteration: g_{k+1} = (g_k + f / g_k) / 2
    Precondition: f[0] = 1
    """
    assert len(f) > 0 and f[0] == 1
    g = [1]
    inv2 = modinv(2)
    m = 1
    while m < n:
        m <<= 1
        f_trunc = list(f[:m]) + [0] * max(0, m - len(f))
        g_padded = list(g) + [0] * max(0, m - len(g))
        inv_g = poly_inv(g_padded, m)
        t = multiply(f_trunc, inv_g)[:m]
        g_new = [0] * m
        for i in range(m):
            gi = g[i] if i < len(g) else 0
            g_new[i] = (gi + t[i]) * inv2 % MOD
        g = g_new
    return g[:n]


def poly_exp(f, n):
    """Compute the first n terms of exp(f(x)) mod x^n.

    Uses Newton's iteration on h(g) = ln(g) - f = 0:
        g_{k+1} = g_k * (1 - ln(g_k) + f) mod x^{2^{k+1}}
    Starting from g_0 = [1] (since f[0] = 0 implies exp(f)[0] = 1).
    Precondition: f[0] = 0
    """
    assert len(f) == 0 or f[0] == 0
    g = [1]
    m = 1
    while m < n:
        m <<= 1
        g_padded = list(g) + [0] * max(0, m - len(g))
        lng = poly_ln(g_padded, m)
        tmp = [0] * m
        for i in range(m):
            fi = f[i] if i < len(f) else 0
            tmp[i] = (fi - lng[i]) % MOD
        tmp[0] = (tmp[0] + 1) % MOD
        g = multiply(g, tmp)[:m]
    return g[:n]


def poly_pow(f, k, n):
    """Compute the first n terms of f(x)^k mod x^n.

    Uses the identity: f^k = exp(k * ln(f))
    Precondition: f[0] = 1, k >= 0
    """
    if k == 0:
        result = [0] * n
        if n > 0:
            result[0] = 1
        return result
    f_padded = list(f) + [0] * max(0, n - len(f))
    lng = poly_ln(f_padded, n)
    klng = [x * k % MOD for x in lng]
    return poly_exp(klng, n)
