#!/usr/bin/env python3
"""
Vinaigrette signature scheme - a simplified UOV/MAYO variant.


This scheme uses multivariate quadratic (MQ) polynomials over a finite field.
The public key consists of m upper-triangular n x n matrices P_1, ..., P_m over F_q.
The "whipped-up" mapping P* sums k evaluations: P*(s_1,...,s_k) = P(s_1) + ... + P(s_k).
A valid signature s for message lambda satisfies P*(s) = H(lambda).
"""

import hashlib

# Scheme parameters
Q = 31       # Field size (prime)
N = 14       # Dimension of each component vector
M = 10       # Number of polynomials
O_DIM = 4    # Oil space dimension
V_DIM = 10   # Vinegar dimension (N - O_DIM)
K = 3        # Whipping factor (K * O_DIM >= M)


def shake256_hash(message):
    """Hash a message string to M elements of F_Q using SHAKE256.

    Takes ceil(ceil(log2(q)) * m / 8) bytes of SHAKE256 output,
    then extracts ceil(log2(q))=5 bit chunks reduced mod q.
    """
    bits_per_elem = 5  # ceil(log2(31)) = 5
    num_bytes = -(-bits_per_elem * M // 8)  # ceiling division
    h = hashlib.shake_256(message.encode()).digest(num_bytes)
    result = []
    bit_pos = 0
    for _ in range(M):
        val = 0
        for b in range(bits_per_elem):
            byte_idx = bit_pos // 8
            bit_idx = bit_pos % 8
            val |= ((h[byte_idx] >> bit_idx) & 1) << b
            bit_pos += 1
        result.append(val % Q)
    return result


def load_public_key(filename):
    """Load public key from file. Format: upper-triangular rows, matrices separated by blank lines."""
    matrices = []
    current_rows = []
    with open(filename) as f:
        for line in f:
            line = line.strip()
            if line == '':
                if current_rows:
                    matrices.append(_reconstruct_upper_tri(current_rows))
                    current_rows = []
            else:
                current_rows.append([int(x) for x in line.split()])
    if current_rows:
        matrices.append(_reconstruct_upper_tri(current_rows))
    return matrices


def _reconstruct_upper_tri(rows):
    """Reconstruct n x n upper triangular matrix from compact row format.

    Row i contains entries P[i][i], P[i][i+1], ..., P[i][n-1].
    """
    n = len(rows[0])  # first row has n elements
    matrix = [[0] * n for _ in range(n)]
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            matrix[i][i + j] = val
    return matrix


def eval_polynomial(matrix, x):
    """Evaluate quadratic form x^T P x mod Q where P is upper triangular."""
    n = len(x)
    val = 0
    for i in range(n):
        for j in range(i, n):
            val = (val + matrix[i][j] * x[i] * x[j]) % Q
    return val


def eval_public_key(matrices, x):
    """Evaluate P(x) = (p_1(x), ..., p_m(x)) mod Q."""
    return [eval_polynomial(mat, x) for mat in matrices]


def eval_whipped(matrices, signature):
    """Evaluate P*(s_1,...,s_k) = P(s_1) + ... + P(s_k) mod Q.

    signature is a flat list of K*N integers.
    """
    result = [0] * M
    for i in range(K):
        x = signature[i * N : (i + 1) * N]
        pval = eval_public_key(matrices, x)
        result = [(r + p) % Q for r, p in zip(result, pval)]
    return result


def verify(matrices, message, signature):
    """Verify that P*(signature) == H(message)."""
    if len(signature) != K * N:
        return False
    if any(s < 0 or s >= Q for s in signature):
        return False
    target = shake256_hash(message)
    actual = eval_whipped(matrices, signature)
    return actual == target


if __name__ == "__main__":
    import sys
    pk = load_public_key("public_key.txt")
    msg = "Forge this signature to prove you broke Vinaigrette"

    if len(sys.argv) > 1:
        sig_file = sys.argv[1]
    else:
        sig_file = "signature.txt"

    with open(sig_file) as f:
        sig = [int(x) for x in f.read().split()]

    if verify(pk, msg, sig):
        print("VALID signature!")
    else:
        print("INVALID signature.")
        target = shake256_hash(msg)
        actual = eval_whipped(pk, sig)
        print(f"  Expected: {target}")
        print(f"  Got:      {actual}")
