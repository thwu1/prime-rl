#!/usr/bin/env python3
"""
Solver for Coppersmith lattice-based RSA cryptanalysis.
Uses Fraction-based LLL for exact arithmetic — no external dependencies.

"""

import json
from math import gcd, isqrt
from fractions import Fraction


# ─── LLL lattice reduction (exact Fraction arithmetic) ────────────────────────

def lll_reduce(basis, delta=Fraction(3, 4)):
    """LLL lattice reduction using exact Fraction arithmetic.
    Rows of basis are the lattice vectors."""
    n = len(basis)
    m = len(basis[0])
    B = [list(row) for row in basis]
    mu = [[Fraction(0)] * n for _ in range(n)]
    Bstar = [[Fraction(0)] * m for _ in range(n)]
    Bnorm = [Fraction(0)] * n

    def update_gs():
        for i in range(n):
            Bstar[i] = [Fraction(x) for x in B[i]]
            for j in range(i):
                if Bnorm[j] == 0:
                    continue
                mu[i][j] = sum(Fraction(B[i][k]) * Bstar[j][k] for k in range(m)) / Bnorm[j]
                for k in range(m):
                    Bstar[i][k] -= mu[i][j] * Bstar[j][k]
            Bnorm[i] = sum(x * x for x in Bstar[i])

    update_gs()
    k = 1
    while k < n:
        for j in range(k - 1, -1, -1):
            if abs(mu[k][j]) > Fraction(1, 2):
                r = round(mu[k][j])
                B[k] = [B[k][i] - r * B[j][i] for i in range(m)]
                update_gs()
        if Bnorm[k] >= (delta - mu[k][k - 1] ** 2) * Bnorm[k - 1]:
            k += 1
        else:
            B[k], B[k - 1] = B[k - 1], B[k]
            update_gs()
            k = max(k - 1, 1)
    return B


# ─── Integer cube root ─────────────────────────────────────────────────────

def icbrt(n):
    """Floor of the cube root of non-negative integer n."""
    if n <= 0:
        return 0
    x = 1 << ((n.bit_length() + 2) // 3)
    while True:
        x1 = (2 * x + n // (x * x)) // 3
        if x1 >= x:
            break
        x = x1
    while x * x * x > n:
        x -= 1
    return x


# ─── Polynomial root finding ──────────────────────────────────────────────

def poly_roots_integer(coeffs):
    """Find integer roots of polynomial coeffs[0] + coeffs[1]*x + ... + coeffs[d]*x^d."""
    while len(coeffs) > 1 and coeffs[-1] == 0:
        coeffs = coeffs[:-1]
    deg = len(coeffs) - 1
    if deg <= 0:
        return []
    if deg == 1:
        a0, a1 = coeffs
        if a1 != 0 and a0 % a1 == 0:
            return [-a0 // a1]
        return []
    if deg == 2:
        return _quadratic_roots(coeffs[0], coeffs[1], coeffs[2])
    if deg == 3:
        return _cubic_roots(coeffs)
    return []


def _quadratic_roots(a0, a1, a2):
    """Integer roots of a2*x^2 + a1*x + a0 = 0."""
    if a2 == 0:
        if a1 == 0:
            return []
        if a0 % a1 == 0:
            return [-a0 // a1]
        return []
    disc = a1 * a1 - 4 * a2 * a0
    if disc < 0:
        return []
    s = isqrt(disc)
    if s * s != disc:
        return []
    roots = []
    for num in [-a1 + s, -a1 - s]:
        denom = 2 * a2
        if denom != 0 and num % denom == 0:
            roots.append(num // denom)
    return roots


def _cubic_roots(coeffs):
    """Find integer roots of a cubic polynomial using Newton's method."""
    a0, a1, a2, a3 = coeffs
    if a3 == 0:
        return poly_roots_integer([a0, a1, a2])
    if a0 == 0:
        return list(set([0] + poly_roots_integer([a1, a2, a3])))

    def f(x):
        return ((a3 * x + a2) * x + a1) * x + a0

    def fp(x):
        return (3 * a3 * x + 2 * a2) * x + a1

    results = set()
    abs_ratio = abs(a0 * a3 * a3)
    if abs_ratio > 0:
        est = icbrt(abs_ratio) // abs(a3)
    else:
        est = 1
    sign = -1 if (a0 > 0) == (a3 > 0) else 1

    starts = [0, 1, -1, sign * est, sign * (est + 1), -sign * est]
    if a1 != 0:
        starts.append(-(a0 // a1))

    for start in starts:
        x = start
        for _ in range(5000):
            fv = f(x)
            if fv == 0:
                results.add(x)
                break
            fpv = fp(x)
            if fpv == 0:
                for c in range(x - 5, x + 6):
                    if f(c) == 0:
                        results.add(c)
                break
            step = fv // fpv
            if step == 0:
                for c in range(x - 5, x + 6):
                    if f(c) == 0:
                        results.add(c)
                break
            x_new = x - step
            if x_new == x:
                break
            x = x_new
    return list(results)


# ─── Base-35 encoding ──────────────────────────────────────────────────────

def from_base35(s):
    result = 0
    for c in s:
        result *= 35
        if "0" <= c <= "9":
            result += ord(c) - ord("0")
        elif "a" <= c <= "y":
            result += ord(c) - ord("a") + 10
    return result


def to_base35(n):
    if n == 0:
        return "0"
    cs = []
    while n > 0:
        d = n % 35
        cs.append(chr(ord("0") + d) if d < 10 else chr(ord("a") + d - 10))
        n //= 35
    return "".join(reversed(cs))


# ─── CRT helpers ───────────────────────────────────────────────────────────

def extended_gcd(a, b):
    old_r, r = a, b
    old_s, s = 1, 0
    old_t, t = 0, 1
    while r != 0:
        q = old_r // r
        old_r, r = r, old_r - q * r
        old_s, s = s, old_s - q * s
        old_t, t = t, old_t - q * t
    return old_r, old_s, old_t


def crt2(r1, m1, r2, m2):
    g, p, _ = extended_gcd(m1, m2)
    if (r2 - r1) % g != 0:
        raise ValueError("No CRT solution")
    lcm_val = m1 // g * m2
    sol = (r1 + m1 * ((r2 - r1) // g) * p) % lcm_val
    return sol, lcm_val


def crt3(r1, m1, r2, m2, r3, m3):
    r12, m12 = crt2(r1, m1, r2, m2)
    return crt2(r12, m12, r3, m3)


# ─── Coppersmith small root finder ────────────────────────────────────────

def coppersmith_small_root(coeffs, modulus, X):
    """Find small root x0 in [0, X) of polynomial f(x) = sum(coeffs[i]*x^i) ≡ 0 (mod modulus)
    using Coppersmith's method with LLL."""
    d = len(coeffs) - 1

    # Build lattice of dimension d+1
    # Columns correspond to [1, x, x^2, ..., x^d]
    # Rows 0..d-1: x^i * modulus (modular shifts)
    # Row d: f(xX) (the polynomial)
    n = d + 1
    M = [[0] * n for _ in range(n)]

    for i in range(d):
        M[i][i] = modulus * (X ** i)

    for i in range(d + 1):
        M[d][i] = (coeffs[i] % modulus) * (X ** i)

    B = lll_reduce(M)

    for row in B:
        # Convert lattice vector to integer polynomial in z (where z = x0)
        # row[i] = g_i * X^i, so g_i = row[i] / X^i
        # Integer polynomial: multiply by X^d to clear: sum(row[i] * X^(d-i) * z^i)
        int_coeffs = [row[i] * X ** (d - i) for i in range(d + 1)]
        g = 0
        for c in int_coeffs:
            g = gcd(g, abs(c))
        if g == 0:
            continue
        int_coeffs = [c // g for c in int_coeffs]

        roots = poly_roots_integer(int_coeffs)
        for r in roots:
            if 0 <= r < X:
                val = sum(coeffs[i] * r ** i for i in range(d + 1))
                if val % modulus == 0:
                    return r
    return None


# ─── Part 1: Coppersmith partial factoring ─────────────────────────────────

def solve_part1(ch):
    """Recover p from N and p_high_bits using LLL on a {N, f, xf} lattice."""
    print("[Part 1] Coppersmith partial factoring")
    N = int(ch["part1_factoring"]["N"])
    a = int(ch["part1_factoring"]["p_high_bits"])
    ub = ch["part1_factoring"]["unknown_bits"]
    X = 1 << ub

    # Lattice basis: {N, f(xX), x*f(xX)} where f(x) = x + a
    # Columns: [constant, x, x^2]
    M = [[N, 0, 0],
         [a, X, 0],
         [0, a * X, X * X]]

    B = lll_reduce(M)

    for row in B:
        r0, r1, r2 = row  # [const, x-coeff, x^2-coeff]
        # Polynomial in z = x0: r2*z^2 + r1*X*z + r0*X^2 = 0
        int_coeffs = [r0 * X * X, r1 * X, r2]
        g = 0
        for c in int_coeffs:
            g = gcd(g, abs(c))
        if g == 0:
            continue
        int_coeffs = [c // g for c in int_coeffs]

        for r in poly_roots_integer(int_coeffs):
            if 0 <= r < X:
                p_cand = a + r
                if 1 < p_cand < N and N % p_cand == 0:
                    q_cand = N // p_cand
                    print(f"  p = {p_cand.bit_length()}-bit, q = {q_cand.bit_length()}-bit")
                    return str(p_cand), str(q_cand)

    raise RuntimeError("Part 1 failed")


# ─── Part 2: Stereotyped message attack ────────────────────────────────────

def solve_part2(ch):
    """Recover suffix of base-35 message encrypted with e=3."""
    print("[Part 2] Stereotyped message attack")
    d = ch["part2_stereotyped_message"]
    N = int(d["N"])
    e = d["e"]
    c = int(d["ciphertext"])
    prefix = d["known_prefix_base35"]
    slen = d["unknown_suffix_length"]

    a = from_base35(prefix) * (35 ** slen)
    X = 35 ** slen

    # f(x) = (a + x)^3 - c mod N
    f_coeffs = [(a ** 3 - c) % N, (3 * a ** 2) % N, (3 * a) % N, 1]

    root = coppersmith_small_root(f_coeffs, N, X)
    if root is not None:
        suffix = to_base35(root).rjust(slen, "0")
        full_msg = from_base35(prefix + suffix)
        if pow(full_msg, e, N) == c:
            print(f"  suffix = {suffix}")
            return suffix

    raise RuntimeError("Part 2 failed")


# ─── Part 3: Hastad broadcast attack ──────────────────────────────────────

def solve_part3(ch):
    """Recover message from three e=3 ciphertexts with linear padding."""
    print("[Part 3] Hastad broadcast attack")
    instances = ch["part3_hastad_broadcast"]["instances"]
    Ns = [int(inst["N"]) for inst in instances]
    bs = [int(inst["b"]) for inst in instances]
    cs = [int(inst["c"]) for inst in instances]

    N_prod = Ns[0] * Ns[1] * Ns[2]

    # g_i(x) = (x + b_i)^3 - c_i  (mod N_i)
    # = x^3 + 3*b_i*x^2 + 3*b_i^2*x + (b_i^3 - c_i)
    # CRT on each coefficient across the three instances
    T = [0, 0, 0, 1]  # [const, x, x^2, x^3]
    for j in range(3):
        coeff_vals = []
        for i in range(3):
            if j == 0:
                coeff_vals.append((bs[i] ** 3 - cs[i]) % Ns[i])
            elif j == 1:
                coeff_vals.append((3 * bs[i] ** 2) % Ns[i])
            elif j == 2:
                coeff_vals.append((3 * bs[i]) % Ns[i])
        T[j], _ = crt3(coeff_vals[0], Ns[0], coeff_vals[1], Ns[1], coeff_vals[2], Ns[2])

    X = 1 << 300

    root = coppersmith_small_root(T, N_prod, X)
    if root is not None and root > 0:
        if all(pow(root + bs[i], 3, Ns[i]) == cs[i] for i in range(3)):
            print(f"  m = {root.bit_length()}-bit integer")
            return str(root)

    raise RuntimeError("Part 3 failed")


# ─── Main ──────────────────────────────────────────────────────────────────

def main():
    with open("/app/challenge/challenge.json") as f:
        challenge = json.load(f)

    answer = {}
    p, q = solve_part1(challenge)
    answer["part1_p"] = p
    answer["part1_q"] = q

    suffix = solve_part2(challenge)
    answer["part2_suffix"] = suffix

    m = solve_part3(challenge)
    answer["part3_message"] = m

    with open("/app/answer.json", "w") as f:
        json.dump(answer, f, indent=2)
    print("\nAll parts solved. Answer written to /app/answer.json")


if __name__ == "__main__":
    main()
