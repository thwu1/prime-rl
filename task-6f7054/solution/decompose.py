"""

Cipher Module Security Evaluation - Solution
=============================================
1. Reverse-engineer the stripped binary to extract substitution tables
2. Analyze their cryptographic properties to confirm the weakness
3. Discover that the S-boxes decompose as L2 . X . L1 where X is modular affine
4. Recover the shared arithmetic core X(x) = a*x + b mod 256
"""

import json
import numpy as np


def extract_permutation_tables(binary_path):
    """Scan a binary for 256-byte permutation tables."""
    with open(binary_path, "rb") as f:
        data = f.read()

    tables = []
    offsets = []
    i = 0
    while i <= len(data) - 256:
        candidate = list(data[i : i + 256])
        if sorted(candidate) == list(range(256)):
            tables.append(candidate)
            offsets.append(i)
            i += 256
        else:
            i += 1
    return tables, offsets


def ddt_row_multiset(sbox_arr):
    """Compute canonical DDT row multiset (invariant under affine equivalence)."""
    N = len(sbox_arr)
    sbox_np = np.array(sbox_arr, dtype=np.int32)
    rows = []
    for dx in range(N):
        shifted = np.arange(N, dtype=np.int32) ^ dx
        dy = sbox_np ^ sbox_np[shifted]
        counts = np.bincount(dy, minlength=N)
        rows.append(tuple(sorted(counts.tolist())))
    return tuple(sorted(rows))


def ddt_fast_invariants(sbox_arr):
    """Compute fast DDT invariants for pre-filtering candidates."""
    N = len(sbox_arr)
    sbox_np = np.array(sbox_arr, dtype=np.int32)
    all_counts = []
    for dx in range(1, N):
        shifted = np.arange(N, dtype=np.int32) ^ dx
        dy = sbox_np ^ sbox_np[shifted]
        counts = np.bincount(dy, minlength=N)
        all_counts.extend(counts.tolist())
    hist = {}
    for c in all_counts:
        hist[c] = hist.get(c, 0) + 1
    diff_unif = max(all_counts)
    return diff_unif, hist


def main():
    binary = "/app/cipher_module"

    print("=" * 60)
    print("PHASE 1: Binary Reverse Engineering")
    print("=" * 60)

    tables, offsets = extract_permutation_tables(binary)
    print(f"Found {len(tables)} permutation table(s) at file offsets: "
          f"{[hex(o) for o in offsets]}")

    if len(tables) < 2:
        print("ERROR: Expected at least 2 substitution tables")
        report = {"vulnerable": False, "core_permutation": None}
        with open("/app/report.json", "w") as f:
            json.dump(report, f)
        return

    for idx, t in enumerate(tables):
        assert sorted(t) == list(range(256)), f"Table {idx} is NOT a permutation"
    print("All extracted tables are valid permutations of {0,...,255}")

    print()
    print("=" * 60)
    print("PHASE 2: Cryptographic Property Analysis")
    print("=" * 60)

    sbox1 = tables[0]
    sbox2 = tables[1]

    du1, hist1 = ddt_fast_invariants(sbox1)
    du2, hist2 = ddt_fast_invariants(sbox2)
    print(f"Table 1 differential uniformity: {du1}")
    print(f"Table 2 differential uniformity: {du2}")

    ddt1 = ddt_row_multiset(sbox1)
    ddt2 = ddt_row_multiset(sbox2)

    if ddt1 == ddt2:
        print("CONFIRMED: Both tables have identical DDT row multiset structure")
        print("=> Strong evidence of shared algebraic origin")
    else:
        print("WARNING: DDT structures differ unexpectedly")

    print()
    print("=" * 60)
    print("PHASE 3: Algebraic Core Recovery")
    print("=" * 60)
    print("Searching for simplest modular-arithmetic permutation...")

    target_du, target_hist = du1, hist1
    target_ddt = ddt1
    N = 256

    for a in range(1, N, 2):  # a must be odd for permutation
        for b in range(N):
            X = [(a * x + b) % N for x in range(N)]

            du, hist = ddt_fast_invariants(X)
            if du != target_du or hist != target_hist:
                continue

            candidate_ddt = ddt_row_multiset(X)
            if candidate_ddt == target_ddt:
                report = {
                    "vulnerable": True,
                    "core_permutation": X
                }
                with open("/app/report.json", "w") as f:
                    json.dump(report, f)
                print(f"\nVULNERABILITY CONFIRMED")
                print(f"Core function: F(x) = {a}*x + {b} mod 256")
                print(f"Result written to /app/report.json")
                return

    print("ERROR: No valid algebraic core found")
    report = {"vulnerable": False, "core_permutation": None}
    with open("/app/report.json", "w") as f:
        json.dump(report, f)


if __name__ == "__main__":
    main()
