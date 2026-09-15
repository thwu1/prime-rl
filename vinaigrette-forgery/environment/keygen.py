#!/usr/bin/env python3
"""
Generate a Vinaigrette (simplified UOV) public key instance.
The oil space is generated randomly and then discarded.
Only the public key matrices and parameters are saved.
"""
import random
import json
import hashlib
import sys

Q = 31
N = 20
M = 16
O_DIM = 4
V = N - O_DIM  # 16
K = 4

random.seed(0x564E4752)  # VNGR

def modinv(a, p):
    """Modular inverse using extended Euclidean algorithm."""
    a = a % p
    if a == 0:
        return None
    g, x, _ = extended_gcd(a, p)
    if g != 1:
        return None
    return x % p

def extended_gcd(a, b):
    if a == 0:
        return b, 0, 1
    g, x, y = extended_gcd(b % a, a)
    return g, y - (b // a) * x, x

def mat_mul(A, B, r1, r2, r3, q):
    C = [[0]*r3 for _ in range(r1)]
    for i in range(r1):
        for j in range(r3):
            s = 0
            for l in range(r2):
                s += A[i][l] * B[l][j]
            C[i][j] = s % q
    return C

def mat_rref(mat, rows, cols, q):
    """Row-reduce a matrix over F_q. Returns (rref, rank, pivot_cols)."""
    M = [row[:] for row in mat]
    pivot_cols = []
    r = 0
    for c in range(cols):
        pivot = -1
        for i in range(r, rows):
            if M[i][c] % q != 0:
                pivot = i
                break
        if pivot == -1:
            continue
        M[r], M[pivot] = M[pivot], M[r]
        inv = modinv(M[r][c], q)
        for j in range(cols):
            M[r][j] = (M[r][j] * inv) % q
        for i in range(rows):
            if i == r:
                continue
            factor = M[i][c] % q
            if factor != 0:
                for j in range(cols):
                    M[i][j] = (M[i][j] - factor * M[r][j]) % q
        pivot_cols.append(c)
        r += 1
    return M, r, pivot_cols

def null_space(mat, rows, cols, q):
    """Compute the null space of a matrix over F_q."""
    rref, rank, pivots = mat_rref(mat, rows, cols, q)
    free_vars = [c for c in range(cols) if c not in pivots]
    basis = []
    for fv in free_vars:
        vec = [0] * cols
        vec[fv] = 1
        for idx, pc in enumerate(pivots):
            vec[pc] = (-rref[idx][fv]) % q
        basis.append(vec)
    return basis

def verify_oil_space(public_keys, O_basis, n, q):
    """Verify that the oil space is in the left null space of each P_k."""
    for k, P in enumerate(public_keys):
        for ob in O_basis:
            # Check ob^T * P = 0
            for j in range(n):
                val = sum(ob[i] * P[i][j] for i in range(n)) % q
                if val != 0:
                    print(f"FAIL: oil vector not in left null space of P_{k}, col {j}")
                    return False
    return True

def verify_quadratic_vanish(public_keys, O_basis, n, q):
    """Verify p_k(o) = 0 for all o in O and all k."""
    for k, P in enumerate(public_keys):
        for ob in O_basis:
            val = sum(P[i][j] * ob[i] * ob[j] for i in range(n) for j in range(n)) % q
            if val != 0:
                print(f"FAIL: quadratic form P_{k} doesn't vanish on oil vector")
                return False
    return True

# Generate random oil space basis O_basis (N x O_DIM)
# Use row-echelon form: first O_DIM rows = identity
O_basis_cols = []
for col_idx in range(O_DIM):
    col = [0] * N
    col[col_idx] = 1
    for i in range(O_DIM, N):
        col[i] = random.randint(0, Q - 1)
    O_basis_cols.append(col)

# O_basis as a list of O_DIM row vectors (each length N)
# Actually we need it as column vectors for the construction
# O_basis_mat[i][j] = j-th component of i-th basis vector
O_basis_mat = [[O_basis_cols[j][i] for j in range(O_DIM)] for i in range(N)]
# So O_basis_mat is N x O_DIM

# Compute basis Q for O^perp (vectors x with O_basis^T x = 0)
# O_basis^T is O_DIM x N: first O_DIM columns form identity
# null space of O_basis^T: x[:O_DIM] = -W^T x[O_DIM:] where W = O_basis_mat[O_DIM:, :]
W = [O_basis_mat[O_DIM + i] for i in range(V)]  # V x O_DIM

Q_basis = []  # V vectors, each length N
for vi in range(V):
    vec = [0] * N
    # Set oil part: vec[:O_DIM] = -W[vi]
    for j in range(O_DIM):
        vec[j] = (-W[vi][j]) % Q
    # Set vinegar part: identity
    vec[O_DIM + vi] = 1
    Q_basis.append(vec)

# Q_mat is N x V
Q_mat = [[Q_basis[j][i] for j in range(V)] for i in range(N)]

# Verify Q_mat^T * O_basis_mat = 0
for qi in range(V):
    for oj in range(O_DIM):
        val = sum(Q_mat[r][qi] * O_basis_mat[r][oj] for r in range(N)) % Q
        if val != 0:
            print(f"ERROR: Q^T * O_basis != 0 at ({qi},{oj})")
            sys.exit(1)

# Generate public key matrices P_k = Q_mat * R_k
# R_k is V x N, random with full row rank
public_keys = []
for kidx in range(M):
    while True:
        R = [[random.randint(0, Q - 1) for _ in range(N)] for _ in range(V)]
        # Check full row rank
        _, rank, _ = mat_rref([row[:] for row in R], V, N, Q)
        if rank == V:
            break
    P = mat_mul(Q_mat, R, N, V, N, Q)
    public_keys.append(P)

# Verify construction
oil_vecs = [[O_basis_cols[j][i] for i in range(N)] for j in range(O_DIM)]
assert verify_oil_space(public_keys, oil_vecs, N, Q), "Oil space verification failed"
assert verify_quadratic_vanish(public_keys, oil_vecs, N, Q), "Quadratic vanishing failed"

# Save public key to file
# Format: each matrix is N lines of N space-separated integers, matrices separated by blank line
with open('/app/public_key.txt', 'w') as f:
    for idx, P in enumerate(public_keys):
        if idx > 0:
            f.write('\n')
        for row in P:
            f.write(' '.join(str(x) for x in row) + '\n')

# Save parameters
params = {
    'q': Q,
    'n': N,
    'm': M,
    'o': O_DIM,
    'k': K,
    'message': 'Mayonnaise is not an instrument'
}
with open('/app/params.json', 'w') as f:
    json.dump(params, f, indent=2)

# Compute and save hash for reference (but NOT the oil space!)
message = params['message']
bits_per_elem = 5
total_bytes = (bits_per_elem * M + 7) // 8
shake = hashlib.shake_256(message.encode()).digest(total_bytes)
bits = ''.join(format(b, '08b') for b in shake)
h = [int(bits[i*5:(i+1)*5], 2) % Q for i in range(M)]
with open('/app/hash_target.txt', 'w') as f:
    f.write(' '.join(str(x) for x in h) + '\n')

print(f"Vinaigrette instance generated: q={Q}, n={N}, m={M}, o={O_DIM}, k={K}")
print(f"Hash target: {h}")
print("Public key saved to /app/public_key.txt")
print("Parameters saved to /app/params.json")
