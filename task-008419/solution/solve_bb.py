#!/usr/bin/env python3

"""
Construct the bivariate bicycle code from /app/code_spec.json,
verify its properties, and benchmark BP+OSD decoding under
code-capacity depolarizing noise.
"""

import json
import numpy as np


def build_cyclic_shift(n, power):
    """Build n x n cyclic permutation matrix S^power."""
    power = power % n
    M = np.zeros((n, n), dtype=np.int8)
    for i in range(n):
        M[i, (i + power) % n] = 1
    return M


def build_polynomial_matrix(l, m, terms):
    """
    Build (l*m) x (l*m) matrix from polynomial terms over Z_l x Z_m.
    Each term [i, j] maps to S_l^i (kron) S_m^j.
    """
    dim = l * m
    result = np.zeros((dim, dim), dtype=np.int8)
    for (i, j) in terms:
        Si = build_cyclic_shift(l, i)
        Tj = build_cyclic_shift(m, j)
        result = (result + np.kron(Si, Tj).astype(np.int8)) % 2
    return result


def gf2_rank(M):
    """Compute rank of binary matrix over GF(2) using Gaussian elimination."""
    mat = M.copy().astype(np.int8)
    nrows, ncols = mat.shape
    rank = 0
    for col in range(ncols):
        pivot_row = -1
        for row in range(rank, nrows):
            if mat[row, col]:
                pivot_row = row
                break
        if pivot_row == -1:
            continue
        mat[[rank, pivot_row]] = mat[[pivot_row, rank]]
        for row in range(nrows):
            if row != rank and mat[row, col]:
                mat[row] = mat[row] ^ mat[rank]
        rank += 1
    return rank


def gf2_rref(M):
    """
    Compute reduced row echelon form over GF(2).
    Returns (rref_rows, pivot_columns).
    """
    mat = M.copy().astype(np.int8)
    nrows, ncols = mat.shape
    pivots = []
    r = 0
    for col in range(ncols):
        pivot_row = -1
        for row in range(r, nrows):
            if mat[row, col]:
                pivot_row = row
                break
        if pivot_row == -1:
            continue
        mat[[r, pivot_row]] = mat[[pivot_row, r]]
        for row in range(nrows):
            if row != r and mat[row, col]:
                mat[row] = mat[row] ^ mat[r]
        pivots.append(col)
        r += 1
    return mat[:r].copy(), pivots


def is_in_rowspace(rref_rows, pivots, vector):
    """Check if binary vector is in the rowspace using precomputed RREF."""
    v = vector.copy().astype(np.int8)
    for i, col in enumerate(pivots):
        if v[col]:
            v = v ^ rref_rows[i]
    return not np.any(v)


def main():
    # Load specification
    with open("/app/code_spec.json") as f:
        spec = json.load(f)

    l = spec["l"]
    m = spec["m"]
    a_terms = [tuple(t) for t in spec["a_terms"]]
    b_terms = [tuple(t) for t in spec["b_terms"]]
    error_rates = spec["error_rates"]
    num_shots = spec["num_shots"]
    seed = spec["seed"]
    osd_order = spec["osd_order"]

    # -----------------------------------------------------------
    # Step 1: Construct the bivariate bicycle code
    # -----------------------------------------------------------
    A = build_polynomial_matrix(l, m, a_terms)
    B = build_polynomial_matrix(l, m, b_terms)

    n = 2 * l * m
    dim = l * m  # = n // 2

    # CSS parity check matrices
    Hx = np.hstack([A, B])       # dim x n
    Hz = np.hstack([B.T, A.T])   # dim x n

    print(f"Hx shape: {Hx.shape}, Hz shape: {Hz.shape}")

    # -----------------------------------------------------------
    # Step 2: Verify code properties
    # -----------------------------------------------------------
    css_check = (Hx @ Hz.T) % 2
    css_valid = bool(np.all(css_check == 0))
    print(f"CSS valid: {css_valid}")

    hx_rank = gf2_rank(Hx)
    hz_rank = gf2_rank(Hz)
    k = n - hx_rank - hz_rank
    print(f"n={n}, k={k}, hx_rank={hx_rank}, hz_rank={hz_rank}")

    # Stabilizer weights
    hx_weights = np.sum(Hx, axis=1)
    hz_weights = np.sum(Hz, axis=1)
    stabilizer_weight = int(hx_weights[0])
    assert np.all(hx_weights == stabilizer_weight), "Hx row weights not uniform"
    assert np.all(hz_weights == stabilizer_weight), "Hz row weights not uniform"
    print(f"Stabilizer weight: {stabilizer_weight}")

    # Precompute RREF for logical error detection
    hx_rref, hx_pivots = gf2_rref(Hx)
    hz_rref, hz_pivots = gf2_rref(Hz)

    # -----------------------------------------------------------
    # Step 3: Set up BP+OSD decoder
    # -----------------------------------------------------------
    try:
        from ldpc import BpOsdDecoder
    except ImportError:
        from ldpc.bposd_decoder import BpOsdDecoder

    osd_method = "osd_0" if osd_order == 0 else "osd_cs"

    # -----------------------------------------------------------
    # Step 4: Monte Carlo simulation
    # -----------------------------------------------------------
    logical_error_rates = {}
    rng = np.random.default_rng(seed)

    for p in error_rates:
        channel_prob = 2.0 * p / 3.0  # effective X (or Z) flip probability

        # Create decoders for this noise level
        decoder_x = BpOsdDecoder(
            Hz.astype(np.float64),
            error_rate=channel_prob,
            bp_method="product_sum",
            max_iter=20,
            schedule="serial",
            osd_method=osd_method,
            osd_order=osd_order,
        )
        decoder_z = BpOsdDecoder(
            Hx.astype(np.float64),
            error_rate=channel_prob,
            bp_method="product_sum",
            max_iter=20,
            schedule="serial",
            osd_method=osd_method,
            osd_order=osd_order,
        )

        num_logical_errors = 0

        for _ in range(num_shots):
            # Sample depolarizing noise
            r = rng.random(n)
            # X error: r < p/3, Y error: p/3 <= r < 2p/3, Z error: 2p/3 <= r < p
            e_x = ((r < p / 3) | ((r >= p / 3) & (r < 2 * p / 3))).astype(np.uint8)
            e_z = (((r >= p / 3) & (r < 2 * p / 3)) | ((r >= 2 * p / 3) & (r < p))).astype(np.uint8)

            # Syndromes
            s_x = (Hz @ e_x) % 2   # syndrome from Z-stabilizers detecting X errors
            s_z = (Hx @ e_z) % 2   # syndrome from X-stabilizers detecting Z errors

            # Decode
            c_x = decoder_x.decode(s_x.astype(np.uint8))
            c_z = decoder_z.decode(s_z.astype(np.uint8))

            # Residual errors
            r_x = (e_x.astype(np.int8) + c_x.astype(np.int8)) % 2
            r_z = (e_z.astype(np.int8) + c_z.astype(np.int8)) % 2

            # Logical error check: residual not in stabilizer rowspace
            x_fail = not is_in_rowspace(hx_rref, hx_pivots, r_x.astype(np.int8))
            z_fail = not is_in_rowspace(hz_rref, hz_pivots, r_z.astype(np.int8))

            if x_fail or z_fail:
                num_logical_errors += 1

        logical_error_rates[str(p)] = num_logical_errors / num_shots
        print(f"p={p}: logical_error_rate={logical_error_rates[str(p)]:.4f}")

    # -----------------------------------------------------------
    # Step 5: Write results
    # -----------------------------------------------------------
    results = {
        "code_parameters": {
            "n": int(n),
            "k": int(k),
            "hx_rank": int(hx_rank),
            "hz_rank": int(hz_rank),
            "css_valid": css_valid,
            "stabilizer_weight": stabilizer_weight,
        },
        "logical_error_rates": logical_error_rates,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
