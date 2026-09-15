#!/usr/bin/env python3
"""
Test the integer LLL on challenge data.
"""
import json
from math import isqrt, gcd, lcm
from fractions import Fraction


def lll_reduce(basis):
    """
    Integer-only LLL lattice reduction (Cohen's Algorithm 2.6.3).
    Avoids all fraction arithmetic by tracking integral Gram-Schmidt invariants.
    basis: list of lists of ints (row vectors).
    Returns: reduced basis as list of lists of ints.
    """
    n = len(basis)
    if n == 0:
        return basis
    m = len(basis[0])
    B = [list(row) for row in basis]

    def dot_vecs(i, j):
        return sum(B[i][k] * B[j][k] for k in range(m))

    # d[i] and lam[i][j] (integral Gram-Schmidt coefficients)
    lam = [[0] * n for _ in range(n)]
    d = [0] * (n + 1)
    d[0] = 1

    # Initialize d and lam
    for i in range(n):
        for j in range(i + 1):
            u = dot_vecs(i, j)
            for k in range(j):
                u = (d[k + 1] * u - lam[i][k] * lam[j][k]) // d[k]
            if i == j:
                d[i + 1] = u
            else:
                lam[i][j] = u

    def reduce_step(k, l):
        if 2 * abs(lam[k][l]) > d[l + 1]:
            # r = round(lam[k][l] / d[l+1])
            q = d[l + 1]
            r = (2 * lam[k][l] + q) // (2 * q)
            B[k] = [B[k][j] - r * B[l][j] for j in range(m)]
            lam[k][l] -= r * d[l + 1]
            for j in range(l):
                lam[k][j] -= r * lam[l][j]

    def swap_step(k):
        B[k], B[k - 1] = B[k - 1], B[k]
        for j in range(k - 1):
            lam[k][j], lam[k - 1][j] = lam[k - 1][j], lam[k][j]

        lam_kk1 = lam[k][k - 1]
        B_val = (d[k + 1] * d[k - 1] + lam_kk1 * lam_kk1) // d[k]

        for i in range(k + 1, n):
            t = lam[i][k]
            lam[i][k] = (d[k - 1] * t - lam_kk1 * lam[i][k - 1]) // d[k]
            lam[i][k - 1] = (B_val * lam[i][k - 1] + lam_kk1 * t) // d[k + 1]

        d[k] = B_val

    k = 1
    while k < n:
        reduce_step(k, k - 1)
        # Lovász: 4*(d[k+1]*d[k-1] + lam[k][k-1]^2) >= 3*d[k]^2
        if 4 * (d[k + 1] * d[k - 1] + lam[k][k - 1] ** 2) < 3 * d[k] ** 2:
            swap_step(k)
            k = max(k - 1, 1)
        else:
            for l in range(k - 2, -1, -1):
                reduce_step(k, l)
            k += 1

    return B


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


def integer_roots_quadratic(a0, a1, a2):
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


def integer_roots_cubic_newton(a0, a1, a2, a3):
    """Find integer roots of a3*x^3 + a2*x^2 + a1*x + a0 using Newton with Fraction."""
    if a3 == 0:
        return integer_roots_quadratic(a0, a1, a2)
    candidates = set()
    if a0 == 0:
        candidates.add(0)
        candidates.update(integer_roots_quadratic(a1, a2, a3))
    # Newton's method with exact Fraction arithmetic
    for start in [0, 1, -1]:
        x = Fraction(start)
        for _ in range(300):
            fx = a3 * x ** 3 + a2 * x ** 2 + a1 * x + a0
            fpx = 3 * a3 * x ** 2 + 2 * a2 * x + a1
            if fpx == 0:
                break
            x_new = x - fx / fpx
            if x_new == x:
                break
            x = x_new
        # Round to nearest integer and check neighbors
        if x.denominator != 0:
            xi = int(x.numerator // x.denominator)
            for c in range(xi - 2, xi + 3):
                if a3 * c ** 3 + a2 * c ** 2 + a1 * c + a0 == 0:
                    candidates.add(c)
    return list(candidates)


def extract_poly_and_roots(B, col_scales, max_root=None):
    """
    From LLL-reduced rows, extract polynomials and find integer roots.
    col_scales[j] is the scaling for column j (e.g., X^(deg-j)).
    Polynomial: sum_j (B[row][j] / col_scales[j]) * x^(deg-j)
    """
    n = len(B)
    deg = n - 1
    for row_idx in range(n):
        # Extract polynomial coefficients [a0, a1, ..., a_deg]
        # Column j corresponds to x^(deg-j)
        raw = []
        for j in range(n):
            raw.append(Fraction(B[row_idx][j], col_scales[j]))

        # raw[j] is the coefficient of x^(deg-j)
        # Rearrange to [a0, a1, ..., a_deg] where a_i is coeff of x^i
        coeffs = list(reversed(raw))

        # Clear denominators
        denoms = [c.denominator for c in coeffs]
        L = denoms[0]
        for dd in denoms[1:]:
            L = lcm(L, dd)
        int_coeffs = [int(c * L) for c in coeffs]

        if all(c == 0 for c in int_coeffs):
            continue

        # Find roots based on degree
        if deg == 2:
            roots = integer_roots_quadratic(int_coeffs[0], int_coeffs[1], int_coeffs[2])
        elif deg == 3:
            roots = integer_roots_cubic_newton(int_coeffs[0], int_coeffs[1], int_coeffs[2], int_coeffs[3])
        else:
            roots = []

        for r in roots:
            if max_root is not None and (r < 0 or r >= max_root):
                continue
            yield row_idx, r, int_coeffs


# Load challenge
with open("/app/challenge/challenge.json") as f:
    ch = json.load(f)

# === Part 1 ===
print("=== Part 1: Coppersmith Partial Factoring ===")
N = int(ch["part1_factoring"]["N"])
a = int(ch["part1_factoring"]["p_high_bits"])
ub = ch["part1_factoring"]["unknown_bits"]
X = 1 << ub

M = [[X*X, 2*X*a, a*a], [0, X, a], [0, 0, N]]
B = lll_reduce(M)
print("LLL done, row bit lengths:", [[abs(v).bit_length() if v else 0 for v in row] for row in B])

col_scales = [X*X, X, 1]
for row_idx, r, _ in extract_poly_and_roots(B, col_scales):
    candidate = a + r
    if candidate > 1 and N % candidate == 0:
        p = candidate
        q = N // p
        print(f"Part 1 SUCCESS: p={p}, q={q}")
        break

# === Part 2 ===
print("\n=== Part 2: Stereotyped Message ===")
ch2 = ch["part2_stereotyped_message"]
N2 = int(ch2["N"])
e = ch2["e"]
c2 = int(ch2["ciphertext"])
prefix = ch2["known_prefix_base35"]
slen = ch2["unknown_suffix_length"]
a2 = from_base35(prefix) * (35**slen)
X2 = 35**slen

M2 = [
    [X2**3, 3*(X2**2)*a2, 3*X2*a2**2, a2**3 - c2],
    [0, N2*X2**2, 0, 0],
    [0, 0, N2*X2, 0],
    [0, 0, 0, N2],
]
print("Running LLL for 4x4...")
B2 = lll_reduce(M2)
print("LLL done")
print("Row bit lengths:", [[abs(v).bit_length() if v else 0 for v in row] for row in B2])

col_scales2 = [X2**3, X2**2, X2, 1]
for row_idx, r, _ in extract_poly_and_roots(B2, col_scales2, max_root=X2):
    suffix = to_base35(r)
    while len(suffix) < slen:
        suffix = "0" + suffix
    full = from_base35(prefix + suffix)
    if pow(full, e, N2) == c2:
        print(f"Part 2 SUCCESS: suffix={suffix}")
        break

# === Part 3 ===
print("\n=== Part 3: Hastad Broadcast ===")
instances = ch["part3_hastad_broadcast"]["instances"]
Ns = [int(inst["N"]) for inst in instances]
bs = [int(inst["b"]) for inst in instances]
cs = [int(inst["c"]) for inst in instances]

def extended_gcd(a, b):
    if a == 0:
        return b, 0, 1
    g, y, x = extended_gcd(b % a, a)
    return g, x - (b // a) * y, y

def crt(r1, m1, r2, m2):
    g, p, q = extended_gcd(m1, m2)
    if (r2 - r1) % g != 0:
        raise ValueError("No CRT solution")
    lcm_val = m1 // g * m2
    sol = (r1 + m1 * ((r2 - r1) // g) * p) % lcm_val
    return sol, lcm_val

def crt3(r1, m1, r2, m2, r3, m3):
    r12, m12 = crt(r1, m1, r2, m2)
    return crt(r12, m12, r3, m3)

coeffs_per = []
for i in range(3):
    c3 = 1
    c2v = 3 * bs[i]
    c1v = 3 * bs[i]**2
    c0v = bs[i]**3 - cs[i]
    coeffs_per.append([c3, c2v, c1v, c0v])

T = [0, 0, 0, 0]
T[0] = 1
for j in range(1, 4):
    r1 = coeffs_per[0][j] % Ns[0]
    r2 = coeffs_per[1][j] % Ns[1]
    r3 = coeffs_per[2][j] % Ns[2]
    val, _ = crt3(r1, Ns[0], r2, Ns[1], r3, Ns[2])
    T[j] = val

N_prod = Ns[0] * Ns[1] * Ns[2]
X3 = 1 << 300

M3 = [
    [N_prod, 0, 0, 0],
    [0, N_prod*X3, 0, 0],
    [0, 0, N_prod*X3*X3, 0],
    [T[3], T[2]*X3, T[1]*X3*X3, X3**3],
]
print("Running LLL for Part 3 4x4...")
B3 = lll_reduce(M3)
print("LLL done")

col_scales3 = [1, X3, X3*X3, X3**3]
for row_idx in range(len(B3)):
    q0 = Fraction(B3[row_idx][0], 1)
    q1 = Fraction(B3[row_idx][1], X3)
    q2 = Fraction(B3[row_idx][2], X3*X3)
    q3 = Fraction(B3[row_idx][3], X3**3)
    denoms = [q0.denominator, q1.denominator, q2.denominator, q3.denominator]
    L = denoms[0]
    for dd in denoms[1:]:
        L = lcm(L, dd)
    int_coeffs = [int(q0*L), int(q1*L), int(q2*L), int(q3*L)]
    if all(c == 0 for c in int_coeffs):
        continue
    roots = integer_roots_cubic_newton(int_coeffs[0], int_coeffs[1], int_coeffs[2], int_coeffs[3])
    for r in roots:
        r = int(r)
        if r > 0 and r.bit_length() <= 300:
            ok = True
            for i in range(3):
                if pow(r + bs[i], 3, Ns[i]) != cs[i]:
                    ok = False
                    break
            if ok:
                print(f"Part 3 SUCCESS: m={r}")
                break
    else:
        continue
    break

print("\nAll parts complete!")
