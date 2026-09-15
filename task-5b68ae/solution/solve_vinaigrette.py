#!/usr/bin/env python3
"""
Vinaigrette signature forging via Kipnis-Shamir attack on balanced UOV.

Attack overview (pure Python, no external algebra system required):
1. Parse decrypted public key matrices P_1, ..., P_m (upper triangular over F_q)
2. Symmetrize: S_k = P_k + P_k^T
3. Compute M = S_a^{-1} S_b for invertible S_a
4. Compute chi = charpoly(M) via Faddeev-LeVerrier over F_q
5. Compute f = sqrt(chi) using coefficient recurrence (chi = f^2 for balanced UOV)
6. Compute ker(f(M)) -- this is exactly the oil space
7. Verify oil vectors via quadratic vanishing condition
8. Use recovered oil space to forge a signature via the whipping-up construction
"""

import hashlib
import math
import os
import random
import sqlite3
import sys


# ==========================================
# Finite field arithmetic over F_q
# ==========================================

def modinv(a, p):
    return pow(a % p, p - 2, p)


def mat_zeros(r, c):
    return [[0] * c for _ in range(r)]


def mat_mul(A, B, r, s, t, q):
    C = mat_zeros(r, t)
    for i in range(r):
        for j in range(t):
            val = 0
            for kk in range(s):
                val += A[i][kk] * B[kk][j]
            C[i][j] = val % q
    return C


def mat_inverse(M, sz, q):
    A = [M[i][:] + [1 if j == i else 0 for j in range(sz)] for i in range(sz)]
    for col in range(sz):
        piv = -1
        for row in range(col, sz):
            if A[row][col] % q != 0:
                piv = row
                break
        if piv == -1:
            return None
        A[col], A[piv] = A[piv], A[col]
        iv = modinv(A[col][col], q)
        for j in range(2 * sz):
            A[col][j] = A[col][j] * iv % q
        for row in range(sz):
            if row != col and A[row][col] % q != 0:
                fac = A[row][col]
                for j in range(2 * sz):
                    A[row][j] = (A[row][j] - fac * A[col][j]) % q
    return [row[sz:] for row in A]


def kernel(A, sz, q):
    A2 = [row[:] for row in A]
    pivots = []
    free = []
    for col in range(sz):
        piv = -1
        for r in range(len(pivots), sz):
            if A2[r][col] % q != 0:
                piv = r
                break
        if piv == -1:
            free.append(col)
            continue
        if piv != len(pivots):
            A2[len(pivots)], A2[piv] = A2[piv], A2[len(pivots)]
        piv_row = len(pivots)
        iv = modinv(A2[piv_row][col], q)
        for j in range(sz):
            A2[piv_row][j] = A2[piv_row][j] * iv % q
        for row in range(sz):
            if row != piv_row and A2[row][col] % q != 0:
                fac = A2[row][col]
                for j in range(sz):
                    A2[row][j] = (A2[row][j] - fac * A2[piv_row][j]) % q
        pivots.append(col)
    basis = []
    for fc in free:
        vec = [0] * sz
        vec[fc] = 1
        for pi, pc in enumerate(pivots):
            vec[pc] = (q - A2[pi][fc]) % q
        basis.append(vec)
    return basis


def eval_quadratic(P, x, n, q):
    val = 0
    for i in range(n):
        for j in range(i, n):
            val += P[i][j] * x[i] * x[j]
    return val % q


def symmetrize(P, n, q):
    S = mat_zeros(n, n)
    for i in range(n):
        for j in range(n):
            S[i][j] = (P[i][j] + P[j][i]) % q
    return S


def compute_hash(message, m, q):
    bits_per = math.ceil(math.log2(q))
    num_bytes = -(-bits_per * m // 8)
    shake = hashlib.shake_256(message.encode())
    hb = shake.digest(num_bytes)
    bits = int.from_bytes(hb, 'big')
    target = []
    for i in range(m):
        val = (bits >> (bits_per * (m - 1 - i))) & ((1 << bits_per) - 1)
        target.append(val % q)
    return target


def parse_public_key(filepath, n, m):
    with open(filepath) as f:
        content = f.read().strip()
    blocks = content.split('\n\n')
    matrices = []
    for block in blocks:
        lines = block.strip().split('\n')
        P = [[0] * n for _ in range(n)]
        for i, line in enumerate(lines):
            vals = list(map(int, line.split()))
            for j, val in enumerate(vals):
                P[i][i + j] = val
        matrices.append(P)
    return matrices


# ==========================================
# Polynomial arithmetic over F_q
# ==========================================

def poly_mul(a, b, q):
    if not a or not b:
        return []
    result = [0] * (len(a) + len(b) - 1)
    for i, ai in enumerate(a):
        for j, bj in enumerate(b):
            result[i + j] = (result[i + j] + ai * bj) % q
    return result


def charpoly_faddeev(M, n, q):
    """Characteristic polynomial via Faddeev-LeVerrier.
    Returns [c0, c1, ..., cn] where chi(x) = c0 + c1*x + ... + cn*x^n.
    Requires q > n (true for q=31, n=12).
    """
    traces = [0] * (n + 1)
    M_power = [[1 if i == j else 0 for j in range(n)] for i in range(n)]
    for k in range(1, n + 1):
        M_power = mat_mul(M_power, M, n, n, n, q)
        traces[k] = sum(M_power[i][i] for i in range(n)) % q

    coeffs = [0] * (n + 1)
    coeffs[n] = 1
    for k in range(1, n + 1):
        s = 0
        for j in range(1, k + 1):
            s = (s + coeffs[n - k + j] * traces[j]) % q
        coeffs[n - k] = (q - s * modinv(k, q)) % q
    return coeffs


def poly_sqrt(chi, q):
    """Compute f such that f^2 = chi over F_q.
    Uses the coefficient recurrence: for chi = f^2 with f monic of degree d,
    f[d-k] = (chi[2d-k] - sum of known cross terms) / (2*f[d]).
    Returns None if chi is not a perfect square.
    """
    chi = [x % q for x in chi]
    while chi and chi[-1] % q == 0:
        chi.pop()
    n = len(chi) - 1
    if n < 0 or n % 2 != 0:
        return None
    d = n // 2

    f = [0] * (d + 1)

    # f[d]^2 = chi[2d]: find a square root of chi[2d] in F_q
    lc = chi[n] % q
    for s in range(q):
        if s * s % q == lc:
            f[d] = s
            break
    else:
        return None

    inv_2fd = modinv(2 * f[d] % q, q)

    for k in range(1, d + 1):
        s = 0
        for i in range(d - k + 1, d):
            j = 2 * d - k - i
            if 0 <= j <= d:
                s = (s + f[i] * f[j]) % q
        f[d - k] = ((chi[2 * d - k] - s) * inv_2fd) % q

    # Verify f^2 == chi
    f2 = poly_mul(f, f, q)
    while f2 and f2[-1] % q == 0:
        f2.pop()
    chi_stripped = chi[:]
    while chi_stripped and chi_stripped[-1] % q == 0:
        chi_stripped.pop()
    if len(f2) != len(chi_stripped):
        return None
    if all((f2[i] - chi_stripped[i]) % q == 0 for i in range(len(chi_stripped))):
        return f
    return None


def eval_poly_matrix(f, M, n, q):
    """Evaluate polynomial f at matrix M: f(M) = f[0]*I + f[1]*M + f[2]*M^2 + ..."""
    result = mat_zeros(n, n)
    M_power = [[1 if i == j else 0 for j in range(n)] for i in range(n)]
    for coeff in f:
        if coeff != 0:
            for i in range(n):
                for j in range(n):
                    result[i][j] = (result[i][j] + coeff * M_power[i][j]) % q
        M_power = mat_mul(M_power, M, n, n, n, q)
    return result


# ==========================================
# Database access
# ==========================================

def get_params():
    conn = sqlite3.connect('/app/vinaigrette.db')
    c = conn.cursor()
    params = {}
    for name, val in c.execute('SELECT param_name, param_value FROM scheme_params'):
        params[name] = val
    conn.close()
    return params


def get_message():
    conn = sqlite3.connect('/app/vinaigrette.db')
    c = conn.cursor()
    c.execute("SELECT content FROM messages WHERE purpose='signing_target'")
    msg = c.fetchone()[0]
    conn.close()
    return msg


# ==========================================
# Kipnis-Shamir attack (kernel of f(M))
# ==========================================

def recover_oil_space(public_keys, q, n, m, o):
    """Recover the o-dimensional oil space using the Kipnis-Shamir attack.

    For balanced UOV (v = o = n/2), M = S_a^{-1} S_b has charpoly chi = f^2.
    The kernel of f(M) is the oil space.
    """
    S_mats = [symmetrize(P, n, q) for P in public_keys]

    for base_idx in range(m):
        S_inv = mat_inverse(S_mats[base_idx], n, q)
        if S_inv is None:
            continue
        print(f"Using S_{base_idx} as invertible base matrix")

        for other_idx in range(m):
            if other_idx == base_idx:
                continue

            M_mat = mat_mul(S_inv, S_mats[other_idx], n, n, n, q)

            # Characteristic polynomial
            chi = charpoly_faddeev(M_mat, n, q)

            # Polynomial square root
            f = poly_sqrt(chi, q)
            if f is None:
                continue

            print(f"  M = S_{base_idx}^-1 * S_{other_idx}: "
                  f"sqrt poly degree {len(f)-1}")

            # Kernel of f(M) = oil space
            fM = eval_poly_matrix(f, M_mat, n, q)
            ker = kernel(fM, n, q)
            print(f"  ker(f(M)) dimension = {len(ker)}")

            if len(ker) < o:
                continue

            # Verify oil vectors via quadratic vanishing condition
            oil_vecs = []
            for vec in ker:
                if all(eval_quadratic(P, vec, n, q) == 0 for P in public_keys):
                    oil_vecs.append(vec)

            print(f"  Oil vectors verified: {len(oil_vecs)}/{len(ker)}")

            if len(oil_vecs) >= o:
                return oil_vecs[:o]

    return None


# ==========================================
# Signature forging
# ==========================================

def forge_signature(oil_vectors, public_keys, message, q, n, m, o, k):
    """Forge a signature using the recovered oil space.

    Uses the whipping-up construction: pick random vinegar vectors,
    solve the resulting linear system using the oil basis.
    """
    S_mats = [symmetrize(P, n, q) for P in public_keys]
    B_oil = oil_vectors
    B_mat = [[B_oil[j][i] for j in range(o)] for i in range(n)]

    target = compute_hash(message, m, q)
    print(f"Hash target: {target}")

    rng = random.Random(42)

    for attempt in range(100):
        v_vecs = [[rng.randint(0, q - 1) for _ in range(n)] for _ in range(k)]

        P_vi = [[eval_quadratic(P, vi, n, q) for P in public_keys]
                 for vi in v_vecs]
        t_prime = [(target[j] - sum(P_vi[i][j] for i in range(k))) % q
                    for j in range(m)]

        # Build linear system
        num_vars = k * o
        system_rows = []
        for j in range(m):
            row = []
            for i in range(k):
                Sj_vi = [sum(S_mats[j][r][c] * v_vecs[i][c]
                             for c in range(n)) % q
                         for r in range(n)]
                BT_Sj_vi = [sum(B_oil[b][r] * Sj_vi[r]
                                for r in range(n)) % q
                            for b in range(o)]
                row.extend(BT_Sj_vi)
            system_rows.append(row)

        # Gaussian elimination on augmented matrix
        aug = [system_rows[j][:] + [t_prime[j]] for j in range(m)]
        pivots = []
        for col in range(num_vars):
            piv = -1
            for r in range(len(pivots), m):
                if aug[r][col] % q != 0:
                    piv = r
                    break
            if piv == -1:
                continue
            if piv != len(pivots):
                aug[len(pivots)], aug[piv] = aug[piv], aug[len(pivots)]
            piv_row = len(pivots)
            iv = modinv(aug[piv_row][col], q)
            for j in range(num_vars + 1):
                aug[piv_row][j] = aug[piv_row][j] * iv % q
            for row in range(m):
                if row != piv_row and aug[row][col] % q != 0:
                    fac = aug[row][col]
                    for j in range(num_vars + 1):
                        aug[row][j] = (aug[row][j] - fac * aug[piv_row][j]) % q
            pivots.append(col)

        # Check consistency
        consistent = True
        for r in range(len(pivots), m):
            if aug[r][num_vars] % q != 0:
                consistent = False
                break
        if not consistent:
            continue

        # Extract solution
        c_vals = [0] * num_vars
        for pi, pc in enumerate(pivots):
            c_vals[pc] = aug[pi][num_vars] % q

        # Build signature vectors: s_i = v_i + B * c_i
        signatures = []
        for i in range(k):
            c_i = c_vals[i * o: (i + 1) * o]
            o_i = [sum(B_mat[r][j] * c_i[j] for j in range(o)) % q
                   for r in range(n)]
            s_i = [(v_vecs[i][r] + o_i[r]) % q for r in range(n)]
            signatures.append(s_i)

        # Internal verification
        total = [0] * m
        for si in signatures:
            for j in range(m):
                total[j] = (total[j] + eval_quadratic(
                    public_keys[j], si, n, q)) % q
        if total == target:
            return signatures

    return None


# ==========================================
# Main
# ==========================================

def main():
    # Load parameters from SQLite database
    params = get_params()
    q = params['q']
    n = params['n']
    m = params['m']
    o = params['o']
    k = params['k']

    print(f"Parameters: q={q}, n={n}, m={m}, o={o}, k={k}")

    # Load decrypted public key
    if not os.path.exists('/app/public_key.txt'):
        print("ERROR: /app/public_key.txt not found.", file=sys.stderr)
        sys.exit(1)
    public_keys = parse_public_key('/app/public_key.txt', n, m)
    print(f"Loaded {len(public_keys)} public key matrices")

    # Load message from database
    message = get_message()
    print(f"Message: {message!r}")

    # Step 1: Kipnis-Shamir attack to recover oil space
    print("\n=== Kipnis-Shamir Attack ===")
    oil_vectors = recover_oil_space(public_keys, q, n, m, o)
    assert oil_vectors is not None, "Oil space recovery failed"
    print(f"Recovered {len(oil_vectors)} oil vectors")

    # Verify oil space
    for vec in oil_vectors:
        for P in public_keys:
            assert eval_quadratic(P, vec, n, q) == 0, \
                "Oil vector verification failed"
    print("Oil space verified")

    # Step 2: Forge signature
    print("\n=== Forging Signature ===")
    signatures = forge_signature(
        oil_vectors, public_keys, message, q, n, m, o, k)
    assert signatures is not None, "Signature forging failed"

    # Write signature
    sig_flat = []
    for si in signatures:
        sig_flat.extend(si)
    with open('/app/signature.txt', 'w') as fout:
        fout.write(' '.join(str(x) for x in sig_flat) + '\n')

    print(f"\nSignature written to /app/signature.txt")
    print(f"Signature: {' '.join(str(x) for x in sig_flat)}")


if __name__ == '__main__':
    main()
