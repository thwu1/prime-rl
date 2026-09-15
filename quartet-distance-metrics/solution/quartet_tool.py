#!/usr/bin/env python3
"""
Quartet distance analysis tool for phylogenetic trees.
Computes pairwise Estabrook et al. (1985) quartet comparison statistics
and similarity metrics between unrooted Newick-format trees.

Uses the compiled C++ tqdist binary for efficient quartet computation,
then derives full (s,d,r1,r2,u) statistics from the binary's
(agreement, unresolved) output using self-comparison algebra.
"""

import json
import os
import subprocess
import sys
from math import comb


def compile_tqdist():
    """Compile the C++ tqdist binary if not already compiled."""
    binary = "/app/tqdist/tqdist"
    if not os.path.isfile(binary):
        result = subprocess.run(
            ["make"], cwd="/app/tqdist",
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            print(f"Compilation failed: {result.stderr}", file=sys.stderr)
            sys.exit(1)
    return binary


def run_tqdist(binary, input_file):
    """Run the tqdist binary and parse its output.

    The binary outputs lines: i j A E Q
    where i >= j (lower triangle + diagonal).
    A = agreement count (quartets resolved identically in both trees)
    E = unresolved-in-both count
    Q = C(n, 4)
    """
    result = subprocess.run(
        [binary, input_file],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        print(f"tqdist failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    pairs = {}
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split()
        i, j = int(parts[0]), int(parts[1])
        A, E, Q = int(parts[2]), int(parts[3]), int(parts[4])
        pairs[(i, j)] = (A, E, Q)
    return pairs


def decompose(ae_pairs, i, j):
    """Derive (s, d, r1, r2, u) from tqdist (A, E) output.

    Key insight: for self-comparison (k,k), A gives total resolved quartets
    in tree k; E gives total unresolved quartets.

    For cross-comparison (i,j):
      A(i,j) = s  (quartets resolved identically in both)
      E(i,j) = u  (quartets unresolved in both)

    Then:
      resolved_i = A(i,i)
      resolved_j = A(j,j)
      d = resolved_i + resolved_j - s - Q + u
      r1 = resolved_i - s - d
      r2 = resolved_j - s - d
    """
    # Cross-comparison pair: stored with larger index first
    big, small = max(i, j), min(i, j)
    A_ij, E_ij, Q = ae_pairs[(big, small)]

    # Self-comparisons
    A_ii = ae_pairs[(i, i)][0]
    A_jj = ae_pairs[(j, j)][0]

    s = A_ij
    u = E_ij
    d = A_ii + A_jj - A_ij - Q + E_ij
    r1 = A_ii - A_ij - d
    r2 = A_jj - A_ij - d

    return Q, s, d, r1, r2, u


def compute_metrics(Q, s, d, r1, r2, u):
    """Compute the 8 Estabrook similarity metrics.

    Formulas derived from the Quartet R package's Metrics.R:
      DoNotConflict:             1 - d/Q
      ExplicitlyAgree:           s/Q
      StrictJointAssertions:     s/(s+d)
      SemiStrictJointAssertions: s/(s+d+u)
      SymmetricDifference:       2s/(2s+2d+r1+r2)
      MarczewskiSteinhaus:       s/(s+2d+r1+r2)
      SteelPenny:                1-(d+r1+r2)/Q
      QuartetDivergence:         1-(2d+r1+r2)/(2Q)
    """
    def safe_div(num, den):
        if den == 0:
            return None
        return round(num / den, 10)

    return {
        "do_not_conflict": safe_div(Q - d, Q),
        "explicitly_agree": safe_div(s, Q),
        "strict_joint_assertions": safe_div(s, s + d),
        "semi_strict_joint_assertions": safe_div(s, s + d + u),
        "symmetric_difference": safe_div(2 * s, 2 * s + 2 * d + r1 + r2),
        "marczewski_steinhaus": safe_div(s, s + 2 * d + r1 + r2),
        "steel_penny": safe_div(Q - d - r1 - r2, Q),
        "quartet_divergence": safe_div(2 * Q - 2 * d - r1 - r2, 2 * Q),
    }


def parse_newick_leaves(s):
    """Parse a Newick string and return leaf labels."""
    s = "".join(s.split())
    if s.endswith(";"):
        s = s[:-1]
    if not s:
        return []

    pos = [0]

    def read_name():
        start = pos[0]
        while pos[0] < len(s) and s[pos[0]] not in "(),:;":
            pos[0] += 1
        return s[start : pos[0]]

    def skip_length():
        if pos[0] < len(s) and s[pos[0]] == ":":
            pos[0] += 1
            while pos[0] < len(s) and s[pos[0]] not in "(),:;":
                pos[0] += 1

    def parse_subtree():
        if pos[0] < len(s) and s[pos[0]] == "(":
            return parse_internal()
        name = read_name()
        return [name] if name else []

    def parse_internal():
        pos[0] += 1  # skip '('
        leaves = []
        while True:
            leaves.extend(parse_subtree())
            skip_length()
            if pos[0] < len(s) and s[pos[0]] == ",":
                pos[0] += 1
            else:
                break
        if pos[0] < len(s) and s[pos[0]] == ")":
            pos[0] += 1
        read_name()  # internal label, ignored
        return leaves

    result = parse_subtree()
    skip_length()
    return result


def main():
    if len(sys.argv) != 4 or sys.argv[2] != "-o":
        print(
            f"Usage: {sys.argv[0]} <input.nwk> -o <output.json>",
            file=sys.stderr,
        )
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[3]

    try:
        with open(input_file) as f:
            lines = [line.strip() for line in f if line.strip()]
    except IOError as e:
        print(f"Error reading input: {e}", file=sys.stderr)
        sys.exit(1)

    if len(lines) < 2:
        print("Error: need at least 2 trees", file=sys.stderr)
        sys.exit(1)

    # Extract leaf labels from each tree
    leaf_sets = [set(parse_newick_leaves(line)) for line in lines]
    ref_leaves = leaf_sets[0]
    if len(ref_leaves) < 4:
        print("Error: need at least 4 leaves", file=sys.stderr)
        sys.exit(1)
    for idx, ls in enumerate(leaf_sets[1:], 1):
        if ls != ref_leaves:
            print(
                f"Error: tree {idx} has different leaf set than tree 0",
                file=sys.stderr,
            )
            sys.exit(1)

    leaves_sorted = sorted(ref_leaves)

    # Compile and run the C++ tqdist binary
    binary = compile_tqdist()
    ae_pairs = run_tqdist(binary, input_file)

    # Compute full statistics and metrics for each pair
    n_trees = len(lines)
    pairwise = []

    for i in range(n_trees):
        for j in range(i + 1, n_trees):
            Q, s, d, r1, r2, u = decompose(ae_pairs, i, j)
            metrics = compute_metrics(Q, s, d, r1, r2, u)
            pairwise.append(
                {
                    "i": i,
                    "j": j,
                    "Q": Q,
                    "s": s,
                    "d": d,
                    "r1": r1,
                    "r2": r2,
                    "u": u,
                    "metrics": metrics,
                }
            )

    result = {
        "num_trees": n_trees,
        "leaf_labels": leaves_sorted,
        "pairwise": pairwise,
    }

    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)


if __name__ == "__main__":
    main()
