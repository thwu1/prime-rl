#!/usr/bin/env python3
"""

Lattice-based private key recovery from DSA signatures with partial nonce leakage.

Uses the CVP inequality solver approach (adapted from rkm0959's toolkit):
the signing equation combined with the nonce decomposition yields a linear system
with bounded unknowns. A lattice is constructed whose points encode feasible
solutions, and Babai's nearest-plane algorithm (after LLL reduction) recovers
the unique solution within the bounds.

Signing equation:  s_i * k_i = h_i + x * r_i  (mod q)
Nonce structure:   k_i = hi_i * 2^176  +  mid_i * 2^80  +  lo_i
Rearranged:        x * r_i  -  s_i * 2^176 * hi_i  -  s_i * lo_i  +  q * val_i
                   =  s_i * 2^80 * mid_i  -  h_i

Uses PARI/GP (via subprocess) for LLL reduction and Babai's CVP computation.
"""

import json
import shutil
import subprocess
import sys


def build_gp_script(M, target, dim):
    """Build a PARI/GP script that performs LLL + Babai CVP."""
    lines = []

    lines.append(f"n = {dim};")
    lines.append("B = matrix(n, n);")
    for i in range(dim):
        for j in range(dim):
            if M[i][j] != 0:
                lines.append(f"B[{j + 1},{i + 1}] = {M[i][j]};")

    lines.append("T = qflll(B);")
    lines.append("R = B * T;")

    lines.append("G = matrix(n, n);")
    lines.append(
        "for(i=1, n,"
        " G[,i] = R[,i];"
        " for(j=1, i-1,"
        "  mu_ij = (R[,i]~ * G[,j]) / (G[,j]~ * G[,j]);"
        "  G[,i] = G[,i] - mu_ij * G[,j]"
        " )"
        ");"
    )

    lines.append("tgt = vectorv(n);")
    for j in range(dim):
        if target[j] != 0:
            lines.append(f"tgt[{j + 1}] = {target[j]};")

    lines.append("diff = tgt;")
    lines.append(
        "forstep(i=n, 1, -1,"
        " c = round((diff~ * G[,i]) / (G[,i]~ * G[,i]));"
        " diff = diff - c * R[,i]"
        ");"
    )
    lines.append("result = tgt - diff;")
    lines.append('for(i=1, n, print(result[i]));')
    lines.append("quit;")

    return "\n".join(lines)


def solve_cvp(sigs, q, num_sigs):
    """
    Build the inequality CVP lattice and solve it using PARI/GP.
    Returns the recovered private key x, or None on failure.
    """
    B_SHIFT = 176
    C_SHIFT = 80
    HI_BITS = 80
    LO_BITS = 80
    dim = 3 * num_sigs + 1

    M = [[0] * dim for _ in range(dim)]
    lb = [0] * dim
    ub = [0] * dim

    for i in range(num_sigs):
        r_i = int(sigs[i]["r"], 16)
        s_i = int(sigs[i]["s"], 16)
        h_i = int(sigs[i]["h"], 16)
        mid_i = int(sigs[i]["leaked_mid"], 16)

        target_i = s_i * (1 << C_SHIFT) * mid_i - h_i

        M[0][i] = r_i
        M[3 * i + 1][i] = -(1 << B_SHIFT) * s_i
        M[3 * i + 2][i] = -s_i
        M[3 * i + 3][i] = q

        lb[i] = target_i
        ub[i] = target_i

    for i in range(num_sigs):
        M[3 * i + 1][num_sigs + 2 * i] = 1
        M[3 * i + 2][num_sigs + 2 * i + 1] = 1
        lb[num_sigs + 2 * i] = 0
        ub[num_sigs + 2 * i] = 1 << HI_BITS
        lb[num_sigs + 2 * i + 1] = 0
        ub[num_sigs + 2 * i + 1] = 1 << LO_BITS

    M[0][dim - 1] = 1
    lb[dim - 1] = 0
    ub[dim - 1] = q

    # Apply CVP inequality scaling
    max_element = 0
    for i in range(dim):
        for j in range(dim):
            max_element = max(max_element, abs(M[i][j]))

    weight = dim * max_element
    max_diff = max(ub[i] - lb[i] for i in range(dim))
    applied_weights = []

    for j in range(dim):
        if lb[j] == ub[j]:
            w = weight
        else:
            w = max_diff // (ub[j] - lb[j])
        applied_weights.append(w)
        for i in range(dim):
            M[i][j] *= w
        lb[j] *= w
        ub[j] *= w

    target = [(lb[j] + ub[j]) // 2 for j in range(dim)]

    # Build and run GP script
    gp_script = build_gp_script(M, target, dim)

    gp_file = "/tmp/cvp_solve.gp"
    with open(gp_file, "w") as f:
        f.write(gp_script)

    print(f"Running GP solver (dim={dim})...", file=sys.stderr)

    try:
        result = subprocess.run(
            ["gp", "-q", "-s", "500000000", gp_file],
            capture_output=True, text=True, timeout=600
        )
    except subprocess.TimeoutExpired:
        print("GP timed out", file=sys.stderr)
        return None

    if result.returncode != 0:
        print(f"GP error (rc={result.returncode}):", file=sys.stderr)
        print(result.stderr[:2000], file=sys.stderr)
        return None

    # Parse output: expect exactly dim integers, one per line
    out_lines = result.stdout.strip().split("\n")
    numeric_lines = []
    for line in out_lines:
        line = line.strip()
        if not line:
            continue
        try:
            int(line)
            numeric_lines.append(line)
        except ValueError:
            pass

    if len(numeric_lines) != dim:
        print(
            f"Expected {dim} numeric lines, got {len(numeric_lines)}",
            file=sys.stderr,
        )
        print(f"stdout tail: {result.stdout[-500:]}", file=sys.stderr)
        print(f"stderr tail: {result.stderr[-500:]}", file=sys.stderr)
        return None

    cvp_result = [int(l) for l in numeric_lines]

    # Extract private key x from the x-bound column
    w_x = applied_weights[dim - 1]
    if w_x == 0:
        print("Weight for x column is 0", file=sys.stderr)
        return None

    x = cvp_result[dim - 1] // w_x
    x = x % q
    return x


def verify_key(x, sigs, q):
    """Verify candidate key x against all signatures via middle-bit check."""
    C_SHIFT = 80
    MID_MASK = (1 << 96) - 1
    for sig in sigs:
        r_i = int(sig["r"], 16)
        s_i = int(sig["s"], 16)
        h_i = int(sig["h"], 16)
        mid_i = int(sig["leaked_mid"], 16)

        s_inv = pow(s_i, q - 2, q)
        k_i = (s_inv * ((h_i + x * r_i) % q)) % q
        mid_check = (k_i >> C_SHIFT) & MID_MASK
        if mid_check != mid_i:
            return False
    return True


def main():
    # Check that PARI/GP is available
    if shutil.which("gp") is None:
        print("ERROR: PARI/GP (gp) not found in PATH.", file=sys.stderr)
        print("Install pari-gp package or ensure gp is on PATH.", file=sys.stderr)
        sys.exit(1)

    with open("/app/data.json") as f:
        data = json.load(f)

    q = int(data["q"], 16)
    sigs = data["signatures"]

    # Try with increasing numbers of signatures for robustness
    for num in [10, 15, 20, 25]:
        if num > len(sigs):
            break
        print(f"\nAttempt with {num} signatures...", file=sys.stderr)
        x = solve_cvp(sigs, q, num)

        if x is None:
            print("  CVP solver returned None", file=sys.stderr)
            continue

        if x <= 0 or x >= q:
            print(f"  Key out of range: {hex(x)}", file=sys.stderr)
            continue

        print(f"  Candidate x = {hex(x)}", file=sys.stderr)

        if verify_key(x, sigs, q):
            print(f"  Verified against all {len(sigs)} signatures!",
                  file=sys.stderr)
            with open("/app/secret_key.txt", "w") as f:
                f.write(hex(x))
            print("Key written to /app/secret_key.txt", file=sys.stderr)
            return
        else:
            print("  Verification failed", file=sys.stderr)

    print("ERROR: all attempts failed", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
