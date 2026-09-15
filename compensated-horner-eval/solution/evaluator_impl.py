#!/usr/bin/env python3
"""
High-accuracy polynomial evaluator using compensated Horner scheme.
Reads from SQLite, writes results back to SQLite.
"""

import json
import sqlite3


def two_sum(a, b):
    """Error-free transformation for addition (Knuth/Moller).
    Returns (s, e) such that a + b = s + e exactly, s = fl(a+b)."""
    s = a + b
    v = s - a
    e = (a - (s - v)) + (b - v)
    return s, e


def _split(a):
    """Veltkamp splitting into two non-overlapping parts."""
    factor = 134217729.0  # 2^27 + 1
    c = factor * a
    ah = c - (c - a)
    al = a - ah
    return ah, al


def two_prod(a, b):
    """Error-free transformation for multiplication (Dekker).
    Returns (p, e) such that a * b = p + e exactly, p = fl(a*b)."""
    p = a * b
    ah, al = _split(a)
    bh, bl = _split(b)
    e = ((ah * bh - p) + ah * bl + al * bh) + al * bl
    return p, e


def naive_horner(coefficients, x):
    """Standard Horner evaluation. coefficients[i] = coeff of x^i."""
    n = len(coefficients) - 1
    result = float(coefficients[n])
    for k in range(n - 1, -1, -1):
        result = result * x + float(coefficients[k])
    return result


def comp_horner(coefficients, x):
    """Compensated Horner evaluation with certified error bound.
    Returns (result, error_bound)."""
    n = len(coefficients) - 1
    if n < 0:
        return 0.0, 0.0
    if n == 0:
        return float(coefficients[0]), 0.0

    u = 2.0 ** -53  # unit roundoff for IEEE 754 binary64

    s = float(coefficients[n])
    sigma = 0.0
    mu = abs(s)
    abs_x = abs(x)

    for k in range(n - 1, -1, -1):
        c_k = float(coefficients[k])
        pi_k, sigma_pi = two_prod(s, x)
        s, sigma_sigma = two_sum(pi_k, c_k)
        sigma = sigma * x + (sigma_pi + sigma_sigma)
        mu = mu * abs_x + abs(c_k)

    result = s + sigma

    two_n_u = 2.0 * n * u
    if two_n_u >= 1.0:
        gamma_2n = float('inf')
    else:
        gamma_2n = two_n_u / (1.0 - two_n_u)

    error_bound = (gamma_2n * gamma_2n * mu
                   + (2 * n + 1) * u * abs(result))

    return result, error_bound


def main():
    conn = sqlite3.connect('/app/polyeval.db')
    conn.row_factory = sqlite3.Row

    polynomials = conn.execute("SELECT * FROM polynomials ORDER BY id").fetchall()

    conn.execute("DROP TABLE IF EXISTS results")
    conn.execute("""
        CREATE TABLE results (
            poly_id INTEGER PRIMARY KEY REFERENCES polynomials(id),
            compensated_value REAL NOT NULL,
            error_bound REAL NOT NULL CHECK(error_bound >= 0),
            naive_value REAL NOT NULL
        )
    """)

    for poly in polynomials:
        coeffs = [float(c) for c in json.loads(poly['coefficients'])]
        x = float(poly['eval_point'])

        naive_val = naive_horner(coeffs, x)
        comp_val, comp_bound = comp_horner(coeffs, x)

        conn.execute(
            "INSERT INTO results (poly_id, compensated_value, error_bound, naive_value) "
            "VALUES (?, ?, ?, ?)",
            (poly['id'], comp_val, comp_bound, naive_val)
        )

    conn.commit()
    conn.close()


if __name__ == '__main__':
    main()
