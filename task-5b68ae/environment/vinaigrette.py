#!/usr/bin/env python3
"""
Vinaigrette Signature Scheme - Reference Implementation

A simplified variant of the MAYO post-quantum signature scheme based on
Unbalanced Oil and Vinegar (UOV) without emulsifier matrices. Uses
a "whipping up" construction to achieve m equations from a small oil space.

Parameters:
  q - prime field order
  n - number of variables (total)
  m - number of equations (polynomials)
  o - oil space dimension
  k - whipping factor (k*o >= m required)

Public key: m upper-triangular n x n matrices over F_q representing
            homogeneous quadratic polynomials.
Secret key: invertible n x n transformation matrix T and central maps.
"""

import json
import hashlib
import random


def modinv(a, p):
    """Modular inverse via Fermat's little theorem."""
    return pow(a % p, p - 2, p)


def mat_mul(A, B, r, s, t, q):
    """Multiply A (r x s) by B (s x t) mod q."""
    C = [[0] * t for _ in range(r)]
    for i in range(r):
        for j in range(t):
            val = 0
            for kk in range(s):
                val += A[i][kk] * B[kk][j]
            C[i][j] = val % q
    return C


def mat_transpose(A, r, c):
    """Transpose A (r x c) -> (c x r)."""
    return [[A[j][i] for j in range(r)] for i in range(c)]


def mat_inverse(M, sz, q):
    """Invert M (sz x sz) mod q via Gauss-Jordan. Returns None if singular."""
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


def rand_invertible(sz, q):
    """Generate a random invertible sz x sz matrix over F_q."""
    while True:
        M = [[random.randint(0, q - 1) for _ in range(sz)] for _ in range(sz)]
        if mat_inverse(M, sz, q) is not None:
            return M


def eval_quadratic(P, x, n, q):
    """Evaluate the quadratic form x^T P x where P is upper triangular."""
    val = 0
    for i in range(n):
        for j in range(i, n):
            val += P[i][j] * x[i] * x[j]
    return val % q


def symmetrize(P, n, q):
    """Compute S = P + P^T (the associated symmetric bilinear form matrix)."""
    S = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            S[i][j] = (P[i][j] + P[j][i]) % q
    return S


def to_upper_triangular(M, n, q):
    """Convert a general matrix to upper-triangular form for a quadratic form.
    The quadratic form x^T U x = x^T M x when U[i][j] = M[i][j] + M[j][i] for i<j
    and U[i][i] = M[i][i]."""
    U = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            if i == j:
                U[i][j] = M[i][j] % q
            else:
                U[i][j] = (M[i][j] + M[j][i]) % q
    return U


def compute_hash(message, m, q):
    """Compute the hash target H(message) in F_q^m using SHAKE256.

    Takes ceil(ceil(log2(q)) * m / 8) bytes from SHAKE256, splits into
    ceil(log2(q))-bit pieces, reduces mod q.
    """
    import math
    bits_per_element = math.ceil(math.log2(q))  # 5 for q=31
    num_bytes = -(-bits_per_element * m // 8)  # ceil division

    shake = hashlib.shake_256(message.encode())
    hash_bytes = shake.digest(num_bytes)
    bits = int.from_bytes(hash_bytes, 'big')

    target = []
    for i in range(m):
        val = (bits >> (bits_per_element * (m - 1 - i))) & ((1 << bits_per_element) - 1)
        target.append(val % q)
    return target


def keygen(q, n, m, o, rng=None):
    """Generate a Vinaigrette key pair.

    Returns (public_keys, secret_key) where:
      public_keys: list of m upper-triangular n x n matrices over F_q
      secret_key: dict with transformation matrix T, its inverse, and central maps
    """
    if rng is None:
        rng = random

    v = n - o  # vinegar dimension

    # Secret transformation
    T = rand_invertible(n, q)
    T_inv = mat_inverse(T, n, q)
    T_t = mat_transpose(T, n, n)

    # Central maps: upper triangular, zero in the o x o (oil x oil) block
    central_maps = []
    for _ in range(m):
        F = [[0] * n for _ in range(n)]
        for i in range(n):
            for j in range(i, n):
                if i >= v and j >= v:
                    F[i][j] = 0  # oil x oil block is zero
                else:
                    F[i][j] = rng.randint(0, q - 1)
        central_maps.append(F)

    # Public key: P_k = T^T F_k T, converted to upper triangular
    public_keys = []
    for F in central_maps:
        temp = mat_mul(F, T, n, n, n, q)
        P = mat_mul(T_t, temp, n, n, n, q)
        public_keys.append(to_upper_triangular(P, n, q))

    secret_key = {
        'T': T,
        'T_inv': T_inv,
        'central_maps': central_maps,
    }
    return public_keys, secret_key


def sign(message, public_keys, secret_key, params, rng=None):
    """Sign a message using the Vinaigrette scheme.

    Requires the secret key (oil space via T_inv).
    Returns signature as list of k vectors, each in F_q^n.
    """
    if rng is None:
        rng = random

    q, n, m, o, k = params['q'], params['n'], params['m'], params['o'], params['k']
    v = n - o
    T_inv = secret_key['T_inv']

    # Oil space basis: last o columns of T_inv
    oil_basis = [[T_inv[r][c] % q for r in range(n)] for c in range(v, n)]

    # Hash target
    target = compute_hash(message, m, q)

    # Symmetrize public keys for bilinear form computation
    S_mats = [symmetrize(P, n, q) for P in public_keys]

    # Oil basis as n x o matrix
    B_mat = [[oil_basis[j][i] for j in range(o)] for i in range(n)]

    # Pick random vinegar vectors
    v_vecs = [[rng.randint(0, q - 1) for _ in range(n)] for _ in range(k)]

    # Compute P(v_i) for each i
    P_vi = [[eval_quadratic(P, vi, n, q) for P in public_keys] for vi in v_vecs]

    # Adjusted target: t' = target - sum P(v_i)
    t_prime = [(target[j] - sum(P_vi[i][j] for i in range(k))) % q for j in range(m)]

    # Build linear system: sum_i M_i c_i = t'
    # M_i[j,:] = (B^T S_j v_i)
    num_vars = k * o
    system_rows = []
    for j in range(m):
        row = []
        for i in range(k):
            Sj_vi = [sum(S_mats[j][r][c] * v_vecs[i][c] for c in range(n)) % q
                     for r in range(n)]
            BT_Sj_vi = [sum(oil_basis[b][r] * Sj_vi[r] for r in range(n)) % q
                        for b in range(o)]
            row.extend(BT_Sj_vi)
        system_rows.append(row)

    # Solve via Gaussian elimination
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

    c_vals = [0] * num_vars
    for pi, pc in enumerate(pivots):
        c_vals[pc] = aug[pi][num_vars] % q

    # Build signatures s_i = v_i + B * c_i
    signatures = []
    for i in range(k):
        c_i = c_vals[i * o: (i + 1) * o]
        o_i = [sum(B_mat[r][j] * c_i[j] for j in range(o)) % q for r in range(n)]
        s_i = [(v_vecs[i][r] + o_i[r]) % q for r in range(n)]
        signatures.append(s_i)

    return signatures


def verify(message, signature, public_keys, params):
    """Verify a Vinaigrette signature.

    signature: list of k vectors, each in F_q^n
    Returns True if valid.
    """
    q, n, m, k = params['q'], params['n'], params['m'], params['k']

    if len(signature) != k:
        return False
    for si in signature:
        if len(si) != n:
            return False
        if not all(0 <= x < q for x in si):
            return False

    target = compute_hash(message, m, q)

    # Compute P*(s) = P(s_1) + ... + P(s_k)
    total = [0] * m
    for si in signature:
        for j in range(m):
            total[j] = (total[j] + eval_quadratic(public_keys[j], si, n, q)) % q

    return total == target


def parse_public_key(filepath, n, m):
    """Parse a public key file.

    Format: m matrices, each as n rows of upper-triangular entries,
    matrices separated by blank lines.
    """
    with open(filepath) as f:
        content = f.read().strip()

    blocks = content.split('\n\n')
    assert len(blocks) == m, f"Expected {m} matrices, got {len(blocks)}"

    matrices = []
    for block in blocks:
        lines = block.strip().split('\n')
        assert len(lines) == n, f"Expected {n} rows, got {len(lines)}"
        P = [[0] * n for _ in range(n)]
        for i, line in enumerate(lines):
            vals = list(map(int, line.split()))
            assert len(vals) == n - i, f"Row {i}: expected {n - i} values, got {len(vals)}"
            for j, val in enumerate(vals):
                P[i][i + j] = val
        matrices.append(P)

    return matrices


def format_signature(signature):
    """Format signature as space-separated integers."""
    flat = []
    for si in signature:
        flat.extend(si)
    return ' '.join(str(x) for x in flat)


def parse_signature(text, n, k):
    """Parse a signature from space-separated text."""
    vals = list(map(int, text.strip().split()))
    assert len(vals) == k * n
    sig = []
    for i in range(k):
        sig.append(vals[i * n: (i + 1) * n])
    return sig
