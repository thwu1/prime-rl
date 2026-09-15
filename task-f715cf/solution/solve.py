#!/usr/bin/env python3
"""
Solve the Vinaigrette signature forgery challenge via birthday/two-sum attack.


Strategy:
  The Vinaigrette scheme (UOV without emulsifier) uses the whipped mapping
  P*(s1,s2,s3) = P(s1) + P(s2) + P(s3), all three evaluations using the
  SAME public key P.  Set s3 = 0 (P(0) = 0), then find s1, s2 such that
  P(s1) + P(s2) = H(message) using a birthday/two-sum collision in the
  10-dimensional image space GF(31)^10.

  Phase 1: generate T random vectors, compute P(v), encode as int64 key,
           store and sort.
  Phase 2: generate random vectors w, compute complement key
           (H(msg) - P(w)) mod 31, binary-search in Phase 1 table.
  Birthday bound: T ~ sqrt(31^10) ~ 31^5 ~ 29M for ~50% success.
  With T = 35M per side, success probability ~75%.
  Multiple rounds with different seeds ensure near-certain success.
"""

import sys
import hashlib
import numpy as np
import time

Q = 31
N = 14
M = 10
K = 3


def shake256_hash(message):
    """Hash message to M elements of GF(Q) using SHAKE256."""
    bits_per_elem = 5
    num_bytes = -(-bits_per_elem * M // 8)
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


def _reconstruct_upper_tri(rows):
    n = len(rows[0])
    matrix = [[0] * n for _ in range(n)]
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            matrix[i][i + j] = val
    return matrix


def load_public_key(filename):
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


def eval_polynomial(matrix, x):
    n = len(x)
    val = 0
    for i in range(n):
        for j in range(i, n):
            val = (val + matrix[i][j] * x[i] * x[j]) % Q
    return val


def eval_whipped(matrices, signature):
    result = [0] * M
    for i in range(K):
        x = signature[i * N : (i + 1) * N]
        for k in range(M):
            result[k] = (result[k] + eval_polynomial(matrices[k], x)) % Q
    return result


def verify(matrices, message, signature):
    if len(signature) != K * N:
        return False
    if any(s < 0 or s >= Q for s in signature):
        return False
    target = shake256_hash(message)
    actual = eval_whipped(matrices, signature)
    return actual == target


def compute_p_and_keys(vectors, pairs, coeff_matrix):
    """Compute P(v) for a batch and encode as int64 keys.

    Uses chunked matrix multiplication to limit memory.
    """
    bs = vectors.shape[0]
    vecs_i64 = vectors.astype(np.int64)
    p_values = np.zeros((bs, M), dtype=np.int64)

    CHUNK = 25
    for start_p in range(0, len(pairs), CHUNK):
        end_p = min(start_p + CHUNK, len(pairs))
        prods = np.empty((bs, end_p - start_p), dtype=np.int64)
        for idx, pi in enumerate(range(start_p, end_p)):
            i, j = pairs[pi]
            prods[:, idx] = vecs_i64[:, i] * vecs_i64[:, j]
        p_values += prods @ coeff_matrix[start_p:end_p]

    p_values = p_values % Q

    keys = np.zeros(bs, dtype=np.int64)
    for k in range(M - 1, -1, -1):
        keys = keys * Q + p_values[:, k]
    return keys, p_values


def main():
    pk = load_public_key("/app/public_key.txt")
    message = "Forge this signature to prove you broke Vinaigrette"
    target = shake256_hash(message)
    print(f"Target hash: {target}")

    # Precompute coefficient matrix: (num_pairs, M)
    pairs = [(i, j) for i in range(N) for j in range(i, N)]
    coeff_matrix = np.zeros((len(pairs), M), dtype=np.int64)
    for p_idx, (i, j) in enumerate(pairs):
        for k in range(M):
            coeff_matrix[p_idx, k] = pk[k][i][j]

    target_arr = np.array(target, dtype=np.int64)

    T = 35_000_000
    BATCH = 500_000

    for round_num in range(5):
        seed1 = 10000 + round_num * 7777
        seed2 = 50000 + round_num * 7777
        t0 = time.time()
        print(f"\nRound {round_num}: T={T}, seeds=({seed1},{seed2})")

        # Phase 1: Build lookup table
        rng1 = np.random.default_rng(seed1)
        all_vectors = np.empty((T, N), dtype=np.uint8)
        all_keys = np.empty(T, dtype=np.int64)

        for start in range(0, T, BATCH):
            end = min(start + BATCH, T)
            bs = end - start
            vecs = rng1.integers(0, Q, size=(bs, N), dtype=np.uint8)
            keys, _ = compute_p_and_keys(vecs, pairs, coeff_matrix)
            all_vectors[start:end] = vecs
            all_keys[start:end] = keys

        print(f"  Phase 1 generated in {time.time()-t0:.1f}s, sorting...")
        sorted_idx = np.argsort(all_keys)
        sorted_keys = all_keys[sorted_idx]
        del all_keys

        t1 = time.time()
        print(f"  Phase 1 done in {t1-t0:.1f}s")

        # Phase 2: Search for complement matches
        rng2 = np.random.default_rng(seed2)
        found = False

        for start in range(0, T, BATCH):
            end = min(start + BATCH, T)
            bs = end - start
            vecs = rng2.integers(0, Q, size=(bs, N), dtype=np.uint8)
            _, p_vals = compute_p_and_keys(vecs, pairs, coeff_matrix)

            complement = (target_arr[np.newaxis, :] - p_vals) % Q
            comp_keys = np.zeros(bs, dtype=np.int64)
            for k in range(M - 1, -1, -1):
                comp_keys = comp_keys * Q + complement[:, k]

            positions = np.searchsorted(sorted_keys, comp_keys)
            clipped = np.minimum(positions, len(sorted_keys) - 1)
            matches = (positions < len(sorted_keys)) & (sorted_keys[clipped] == comp_keys)

            if np.any(matches):
                match_indices = np.where(matches)[0]
                for idx in match_indices:
                    pos = int(positions[idx])
                    s1 = all_vectors[sorted_idx[pos]].astype(int).tolist()
                    s2 = vecs[idx].astype(int).tolist()
                    s3 = [0] * N
                    sig = s1 + s2 + s3

                    if verify(pk, message, sig):
                        with open("/app/signature.txt", "w") as f:
                            f.write(" ".join(str(x) for x in sig) + "\n")
                        print(f"  Signature forged in {time.time()-t0:.1f}s")
                        print(f"  Written to /app/signature.txt")
                        return

        del all_vectors, sorted_keys, sorted_idx
        print(f"  Round {round_num} no match ({time.time()-t0:.1f}s)")

    print("ERROR: Could not forge signature after all rounds")
    sys.exit(1)


if __name__ == "__main__":
    main()
