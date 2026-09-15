#!/usr/bin/env python3

"""
Attack on Vinaigrette (simplified UOV without emulsifier matrices).

The attack exploits the fact that each public key matrix P_k has the
oil space O as its left null space: o^T P_k = 0 for all o in O.
This means the oil space can be recovered by computing the common
left null space of the public key matrices (equivalently, the common
right null space of their transposes).

Once the oil space is known, forging a signature proceeds by:
1. Choosing random vinegar vectors v_i
2. Computing the hash target H(lambda)
3. Solving a linear system over F_q for oil corrections
4. Assembling the signature s_i = v_i + oil_correction_i
"""

import json
import hashlib
import galois
import numpy as np


def load_params():
    with open('/app/params.json', 'r') as f:
        return json.load(f)


def load_public_key(params, GF):
    """Load m matrices of size n x n."""
    q = params['q']
    n = params['n']
    m = params['m']
    with open('/app/public_key.txt', 'r') as f:
        content = f.read().strip()
    blocks = content.split('\n\n')
    matrices = []
    for block in blocks:
        rows = block.strip().split('\n')
        mat = []
        for row in rows:
            vals = [int(x) % q for x in row.split()]
            mat.append(vals)
        matrices.append(GF(mat))
    return matrices


def compute_hash(message, q, m):
    """Compute H(lambda) using SHAKE256 with 5-bit extraction."""
    bits_per_elem = 5
    total_bytes = (bits_per_elem * m + 7) // 8
    shake = hashlib.shake_256(message.encode('utf-8')).digest(total_bytes)
    bits = ''.join(format(b, '08b') for b in shake)
    result = []
    for i in range(m):
        val = int(bits[i * 5:(i + 1) * 5], 2) % q
        result.append(val)
    return result


def find_oil_space(pk_matrices, GF, n, m):
    """
    Find the oil space by computing the common left null space of P_k.

    The left null space of P_k is {x : x^T P_k = 0} = {x : P_k^T x = 0}.
    We compute the right null space of P_k^T for several P_k and intersect.
    """
    # Start with the null space of P_0^T
    P0T = pk_matrices[0].T
    oil_space = P0T.null_space()

    # Intersect with null spaces of other P_k^T to refine
    for k in range(1, m):
        PkT = pk_matrices[k].T
        ns_k = PkT.null_space()

        # Intersect: find vectors in oil_space that are also in ns_k
        # A vector v in oil_space satisfies P_0^T v = 0.
        # We need it to also satisfy P_k^T v = 0.
        # Express v = oil_space^T * alpha, then P_k^T * oil_space^T * alpha = 0
        # i.e., (P_k^T @ oil_space.T) alpha = 0

        if oil_space.shape[0] == 0:
            break

        constraint = PkT @ oil_space.T
        # Find alpha in null space of constraint
        alpha_ns = constraint.null_space()
        if alpha_ns.shape[0] == 0:
            oil_space = GF(np.zeros((0, n), dtype=int))
            break
        # New oil space basis: alpha_ns @ oil_space
        oil_space = alpha_ns @ oil_space

    return oil_space


def eval_quadratic_gf(P, x, GF):
    """Evaluate x^T P x over GF, returning a GF element."""
    return x @ P @ x


def eval_quadratic_int(P, x, q):
    """Evaluate x^T P x mod q, returning a Python int."""
    n = len(x)
    result = 0
    for i in range(n):
        for r in range(n):
            result += int(P[i][r]) * int(x[i]) * int(x[r])
    return result % q


def forge_signature(pk_matrices, oil_basis, target_hash, params, GF):
    """
    Forge a signature using the recovered oil space.

    Steps:
    1. Choose random vinegar vectors v_1, ..., v_k
    2. Compute c_j = H(lambda)_j - sum_i p_j(v_i) for each j
    3. Set up linear system: for each j,
       sum_i v_i^T (P_j + P_j^T) O_basis alpha_i = c_j
    4. Solve for alpha_1, ..., alpha_k
    5. Return s_i = v_i + O_basis^T alpha_i
    """
    q = params['q']
    n = params['n']
    m = params['m']
    o = params['o']
    k = params['k']

    # oil_basis is o x n; O_cols is n x o
    O_cols = oil_basis.T

    # Symmetrize the public key matrices
    sym_matrices = [P + P.T for P in pk_matrices]

    max_attempts = 100
    for attempt in range(max_attempts):
        # Choose random vinegar vectors
        vinegar = [GF.Random(n) for _ in range(k)]

        # Compute the constant part: c_j = target_j - sum_i p_j(v_i)
        c = GF(target_hash)
        for j in range(m):
            for v_i in vinegar:
                c[j] -= eval_quadratic_gf(pk_matrices[j], v_i, GF)

        # Set up the linear system M @ alpha = c
        # M is m x (k*o)
        # M[j, i*o + l] = v_i^T S_j O_cols[:, l]
        M_mat = GF.Zeros((m, k * o))
        for j in range(m):
            S_j = sym_matrices[j]
            for i in range(k):
                row_contribution = vinegar[i] @ S_j @ O_cols
                for l in range(o):
                    M_mat[j, i * o + l] = row_contribution[l]

        # Check if M is invertible (m == k*o should hold)
        assert m == k * o, f"System is not square: {m} != {k * o}"

        # Use galois to compute rank
        try:
            M_rref = M_mat.row_reduce()
        except Exception:
            continue

        # Check rank by counting non-zero rows in RREF
        rk = sum(1 for row in M_rref if any(int(v) != 0 for v in row))
        if rk < m:
            continue

        # Solve M alpha = c using augmented matrix row reduction
        try:
            aug = np.hstack([M_mat, c.reshape(-1, 1)])
            aug = GF(aug)
            aug_rref = aug.row_reduce()
            alpha = aug_rref[:, -1]
        except Exception:
            continue

        # Verify M @ alpha == c
        check = M_mat @ alpha
        if not np.array_equal(check, c):
            continue

        # Assemble signature: s_i = v_i + O_cols @ alpha_i
        signature = []
        for i in range(k):
            alpha_i = alpha[i * o:(i + 1) * o]
            s_i = vinegar[i] + (O_cols @ alpha_i)
            signature.append(s_i)

        return signature

    raise RuntimeError("Failed to forge signature after max attempts")


def main():
    params = load_params()
    q = params['q']
    n = params['n']
    m = params['m']

    GF = galois.GF(q)

    # Load public key
    pk_matrices = load_public_key(params, GF)
    print(f"Loaded {len(pk_matrices)} public key matrices ({n}x{n} over GF({q}))")

    # Step 1: Recover oil space
    print("Recovering oil space...")
    oil_basis = find_oil_space(pk_matrices, GF, n, m)
    print(f"Oil space dimension: {oil_basis.shape[0]}")
    assert oil_basis.shape[0] == params['o'], \
        f"Expected oil space dim {params['o']}, got {oil_basis.shape[0]}"

    # Verify: each oil vector should satisfy o^T P_k o = 0 for all k
    for i in range(oil_basis.shape[0]):
        o_vec = oil_basis[i]
        for j, P in enumerate(pk_matrices):
            val = eval_quadratic_int(P, o_vec, q)
            assert val == 0, f"Oil vector {i} doesn't vanish on P_{j}"
    print("Oil space verified.")

    # Step 2: Compute hash target
    target_hash = compute_hash(params['message'], q, m)
    print(f"Hash target: {target_hash}")

    # Step 3: Forge signature
    print("Forging signature...")
    signature = forge_signature(pk_matrices, oil_basis, target_hash, params, GF)

    # Step 4: Verify locally
    print("Verifying signature locally...")
    for j in range(m):
        total = 0
        for s_i in signature:
            total += eval_quadratic_int(pk_matrices[j], s_i, q)
        total = total % q
        assert total == target_hash[j], \
            f"Local verification failed for poly {j}: {total} != {target_hash[j]}"
    print("Signature verified locally!")

    # Step 5: Write signature
    flat = []
    for s_i in signature:
        flat.extend([int(x) for x in s_i])

    with open('/app/signature.txt', 'w') as f:
        f.write(' '.join(str(x) for x in flat) + '\n')

    print(f"Signature written to /app/signature.txt ({len(flat)} values)")


if __name__ == '__main__':
    main()
