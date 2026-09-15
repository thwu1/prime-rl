
"""
Lattice-based private key recovery from DSA signatures with partial nonce leakage.

Uses the CVP inequality solver approach: the signing equation combined with the
nonce decomposition yields a linear system with bounded unknowns. A lattice is
constructed whose points encode feasible solutions, and Babai's nearest-plane
algorithm (after LLL reduction) recovers the unique solution within the bounds.

Signing equation:  s_i * k_i = h_i + x * r_i  (mod q)
Nonce structure:   k_i = hi_i * 2^176  +  mid_i * 2^80  +  lo_i
Rearranged:        x * r_i  -  s_i * 2^176 * hi_i  -  s_i * lo_i  +  q * val_i
                   =  s_i * 2^80 * mid_i  -  h_i
"""

import json
import sys

from sage.modules.free_module_integer import IntegerLattice
from sage.all import matrix, ZZ, vector, copy


# ---------------------------------------------------------------------------
# CVP solver (adapted from rkm0959's inequality CVP toolkit)
# ---------------------------------------------------------------------------

def Babai_CVP(mat, target):
    M = IntegerLattice(mat, lll_reduce=True).reduced_basis
    G = M.gram_schmidt()[0]
    diff = target
    for i in reversed(range(G.nrows())):
        diff -= M[i] * ((diff * G[i]) / (G[i] * G[i])).round()
    return target - diff


def solve(mat, lb, ub, weight=None):
    mat, lb, ub = copy(mat), copy(lb), copy(ub)
    num_var = mat.nrows()
    num_ineq = mat.ncols()

    max_element = 0
    for i in range(num_var):
        for j in range(num_ineq):
            max_element = max(max_element, abs(mat[i, j]))

    if weight is None:
        weight = num_ineq * max_element

    assert len(lb) == num_ineq
    assert len(ub) == num_ineq

    for i in range(num_ineq):
        assert lb[i] <= ub[i], f"lb > ub at index {i}"

    # Scaling: normalise bound ranges so CVP respects tight constraints
    max_diff = max([ub[i] - lb[i] for i in range(num_ineq)])
    applied_weights = []

    for i in range(num_ineq):
        ineq_weight = weight if lb[i] == ub[i] else max_diff // (ub[i] - lb[i])
        applied_weights.append(ineq_weight)
        for j in range(num_var):
            mat[j, i] *= ineq_weight
        lb[i] *= ineq_weight
        ub[i] *= ineq_weight

    # Find closest lattice vector to the bound midpoint
    target = vector(ZZ, [(lb[i] + ub[i]) // 2 for i in range(num_ineq)])
    result = Babai_CVP(mat, target)

    for i in range(num_ineq):
        if not (lb[i] <= result[i] <= ub[i]):
            print(f"Warning: bound violated at index {i}", file=sys.stderr)

    return result, applied_weights


# ---------------------------------------------------------------------------
# Main solver
# ---------------------------------------------------------------------------

def main():
    # Load challenge data
    with open("/app/data.json") as f:
        data = json.load(f)

    q = int(data["q"], 16)
    sigs = data["signatures"]

    NUM = 10  # number of signatures to use
    B_SHIFT = 176   # bit position of high unknown part
    C_SHIFT = 80    # bit position of middle (leaked) part
    HI_BITS = 80    # bits in unknown high part
    LO_BITS = 80    # bits in unknown low part

    # Build the (3*NUM+1) x (3*NUM+1) lattice matrix
    # Variables (rows):  x (row 0), then per signature i: hi_i (3i+1), lo_i (3i+2), val_i (3i+3)
    # Constraints (cols): equation_i (col i), hi_i_bound (col NUM+2i), lo_i_bound (col NUM+2i+1), x_bound (col 3*NUM)
    dim = 3 * NUM + 1
    M = matrix(ZZ, dim, dim)
    lb = [0] * dim
    ub = [0] * dim

    for i in range(NUM):
        r_i = int(sigs[i]["r"], 16)
        s_i = int(sigs[i]["s"], 16)
        h_i = int(sigs[i]["h"], 16)
        mid_i = int(sigs[i]["leaked_mid"], 16)

        # Equation column i (equality constraint):
        # x * r_i  -  s_i * 2^B * hi_i  -  s_i * lo_i  +  q * val_i  =  target_i
        target_i = s_i * (2**C_SHIFT) * mid_i - h_i

        M[0, i] = r_i                        # x coefficient
        M[3*i + 1, i] = -(2**B_SHIFT) * s_i  # hi_i coefficient
        M[3*i + 2, i] = -s_i                 # lo_i coefficient
        M[3*i + 3, i] = q                    # val_i coefficient

        lb[i] = target_i
        ub[i] = target_i

    for i in range(NUM):
        # Bound columns for hi_i and lo_i
        M[3*i + 1, NUM + 2*i] = 1
        M[3*i + 2, NUM + 2*i + 1] = 1
        lb[NUM + 2*i] = 0
        ub[NUM + 2*i] = 2**HI_BITS
        lb[NUM + 2*i + 1] = 0
        ub[NUM + 2*i + 1] = 2**LO_BITS

    # Bound column for x
    M[0, 3*NUM] = 1
    lb[3*NUM] = 0
    ub[3*NUM] = q

    print(f"Lattice dimension: {dim}x{dim}", file=sys.stderr)
    print("Running CVP solver (LLL + Babai)...", file=sys.stderr)

    result, weights = solve(M, lb, ub)

    # Extract private key x (undo the scaling weight on the x-bound column)
    x = ZZ(result[3*NUM]) // ZZ(weights[3*NUM])
    print(f"Recovered x = {hex(int(x))}", file=sys.stderr)

    # Verify against a few signatures
    verified = 0
    for sig in sigs:
        r_i = int(sig["r"], 16)
        s_i = int(sig["s"], 16)
        h_i = int(sig["h"], 16)
        mid_i = int(sig["leaked_mid"], 16)

        s_inv = pow(int(s_i), int(q) - 2, int(q))
        k_i = (s_inv * ((h_i + int(x) * r_i) % int(q))) % int(q)
        mid_check = (k_i >> C_SHIFT) & ((1 << 96) - 1)
        if mid_check == mid_i:
            verified += 1

    print(f"Verified {verified}/{len(sigs)} signatures", file=sys.stderr)

    if verified == len(sigs):
        key_hex = hex(int(x))
        with open("/app/secret_key.txt", "w") as f:
            f.write(key_hex)
        print(f"Key written to /app/secret_key.txt", file=sys.stderr)
    else:
        print("ERROR: verification failed, key may be wrong", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
