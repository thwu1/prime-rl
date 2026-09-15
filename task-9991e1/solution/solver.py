"""
S-box audit solver: extracts S-boxes from ELF object file, identifies the
algebraically weak one via degree analysis, then recovers its decomposition
as S(x) = A( (a*B(x)+b) mod 256 ) where A,B are GF(2)-linear bijections.

Strategy:
1. Parse the ELF object file using pyelftools to extract the four S-box tables
   by reading symbols from the symbol table and data from sections.
2. For each S-box, compute the algebraic degree of its coordinate Boolean
   functions. The weak S-box will show a "staircase" pattern (degrees
   1,2,3,4,5,5,6,7 or similar) rather than the expected max degree 7 for
   all coordinates of a random permutation.
3. Use DDT (Differential Distribution Table) row profile matching to identify
   the modular arithmetic parameters (a,b) and recover the linear maps A, B.
"""


import json
import struct
import subprocess
import sys

N = 8


def extract_sboxes_from_elf(obj_path):
    """Extract all four S-box tables from the ELF object file using objdump."""
    # Get symbol table
    result = subprocess.run(
        ["nm", "--print-size", obj_path],
        capture_output=True, text=True
    )
    symbols = {}
    for line in result.stdout.strip().split('\n'):
        parts = line.split()
        if len(parts) >= 4:
            addr = int(parts[0], 16)
            size = int(parts[1], 16)
            name = parts[3]
            if name.startswith('SBOX_T'):
                symbols[name] = (addr, size)

    # Get raw section data using objdump
    result = subprocess.run(
        ["objdump", "-s", "-j", ".rodata", obj_path],
        capture_output=True, text=True
    )

    # Parse the hex dump from objdump
    raw_bytes = {}
    current_offset = 0
    hex_data = bytearray()

    for line in result.stdout.split('\n'):
        line = line.strip()
        if not line or not line[0].isspace() and not line[0].isdigit():
            continue
        # Lines look like: " 0000 b4e0ec18 2caa..."
        parts = line.split()
        if len(parts) >= 2:
            try:
                addr = int(parts[0], 16)
            except ValueError:
                continue
            for p in parts[1:]:
                if len(p) <= 8 and all(c in '0123456789abcdef' for c in p):
                    hex_data.extend(bytes.fromhex(p))

    # Extract tables by symbol offset
    sbox_tables = {}
    for name in sorted(symbols.keys()):
        addr, size = symbols[name]
        table_id = int(name[-1])
        table_data = list(hex_data[addr:addr + size])
        sbox_tables[table_id] = table_data

    return sbox_tables


def int_to_bits(x):
    return [(x >> i) & 1 for i in range(N)]


def bits_to_int(bits):
    return sum(b << i for i, b in enumerate(bits))


def algebraic_degree_of_function(f, n):
    """Compute the algebraic degree of a Boolean function f: {0,1}^n -> {0,1}
    given as a list of 2^n values, using the Moebius transform (ANF)."""
    size = 1 << n
    anf = list(f)
    for i in range(n):
        step = 1 << i
        for j in range(size):
            if j & step:
                anf[j] ^= anf[j ^ step]
    max_deg = 0
    for j in range(size):
        if anf[j]:
            deg = bin(j).count('1')
            if deg > max_deg:
                max_deg = deg
    return max_deg


def compute_degree_profile(sbox):
    """Compute algebraic degrees of all coordinate functions and their
    linear combinations. Returns a signature useful for weakness detection."""
    n = N
    size = 256
    coord_degrees = []

    # Individual coordinate function degrees
    for bit in range(n):
        f = [(sbox[x] >> bit) & 1 for x in range(size)]
        deg = algebraic_degree_of_function(f, n)
        coord_degrees.append(deg)

    # Check linear combinations for staircase pattern
    # For a decomposition S = A(f(B(x))), certain linear combinations of
    # output bits will have reduced algebraic degree
    min_combo_degrees = []
    for num_bits in range(1, n + 1):
        min_deg = n
        # Check all linear combinations using exactly num_bits bits
        for mask in range(1, 1 << n):
            if bin(mask).count('1') > num_bits:
                continue
            f = [0] * size
            for x in range(size):
                val = sbox[x]
                bit = 0
                m = mask
                while m:
                    if m & 1:
                        bit ^= val & 1
                    m >>= 1
                    val >>= 1
                f[x] = bit
            deg = algebraic_degree_of_function(f, n)
            if deg < min_deg:
                min_deg = deg
        min_combo_degrees.append(min_deg)

    return coord_degrees, min_combo_degrees


def identify_weak_sbox(sbox_tables):
    """Identify which S-box has anomalously low algebraic complexity."""
    best_id = -1
    best_score = float('inf')

    for table_id, sbox in sbox_tables.items():
        # Quick check: compute degree of all coordinate functions
        coord_degs, combo_degs = compute_degree_profile(sbox)

        # A strong 8-bit S-box should have all coordinate combinations
        # achieving degree 7. The weak one will have a "staircase":
        # some combinations achieve only degree 1, 2, 3, etc.
        score = sum(combo_degs)
        print(f"Table T{table_id}: coord_degrees={coord_degs}, "
              f"min_combo_degrees={combo_degs}, score={score}",
              file=sys.stderr)

        if score < best_score:
            best_score = score
            best_id = table_id

    return best_id


def mat_vec_gf2(M, v):
    return [sum(M[i][j] & v[j] for j in range(N)) % 2 for i in range(N)]


def mat_inv_gf2(M):
    n = len(M)
    aug = [M[i][:] + [1 if j == i else 0 for j in range(n)] for i in range(n)]
    for col in range(n):
        pivot = -1
        for row in range(col, n):
            if aug[row][col] == 1:
                pivot = row
                break
        if pivot == -1:
            return None
        aug[col], aug[pivot] = aug[pivot], aug[col]
        for row in range(n):
            if row != col and aug[row][col] == 1:
                for j in range(2 * n):
                    aug[row][j] ^= aug[col][j]
    return [aug[i][n:] for i in range(n)]


def ddt_row_profile(perm, delta):
    """Compute the sorted value distribution of DDT row at input difference delta."""
    row = {}
    for x in range(256):
        gamma = perm[x] ^ perm[x ^ delta]
        row[gamma] = row.get(gamma, 0) + 1
    return tuple(sorted(row.values()))


def ddt_row_multiset(perm):
    """Compute multiset of DDT row profiles."""
    row_sigs = []
    for delta in range(1, 256):
        row_sigs.append(ddt_row_profile(perm, delta))
    return tuple(sorted(row_sigs))


def decompose_sbox(sbox):
    """Recover A, B (GF(2)-linear) and (a, b) such that
    S(x) = A( (a*B(x)+b) mod 256 ) for all x."""

    # Precompute S-box DDT row profiles
    s_profiles = {}
    for d in range(1, 256):
        s_profiles[d] = ddt_row_profile(sbox, d)
    s_row_multiset = tuple(sorted(s_profiles.values()))

    # Step 1: Find candidate (a, b) pairs via DDT row multiset matching
    candidates = []
    for a in range(1, 256, 2):
        for b in range(256):
            x_perm = [(a * x + b) % 256 for x in range(256)]
            x_multiset = ddt_row_multiset(x_perm)
            if x_multiset == s_row_multiset:
                candidates.append((a, b))
                break

    valid_pairs = []
    candidate_as = list(set(a for a, b in candidates))
    for a in candidate_as:
        for b in range(256):
            x_perm = [(a * x + b) % 256 for x in range(256)]
            x_multiset = ddt_row_multiset(x_perm)
            if x_multiset == s_row_multiset:
                valid_pairs.append((a, b))

    print(f"Found {len(valid_pairs)} candidate (a,b) pairs", file=sys.stderr)

    # Step 2: For each (a, b), try to recover B via DDT row profile matching
    for a_val, b_val in valid_pairs:
        x_perm = [(a_val * x + b_val) % 256 for x in range(256)]

        x_profile_to_deltas = {}
        for d in range(1, 256):
            prof = ddt_row_profile(x_perm, d)
            if prof not in x_profile_to_deltas:
                x_profile_to_deltas[prof] = []
            x_profile_to_deltas[prof].append(d)

        col_candidates = {}
        for i in range(N):
            ei = 1 << i
            s_prof = s_profiles[ei]
            col_candidates[i] = x_profile_to_deltas.get(s_prof, [])

        if any(len(col_candidates[i]) == 0 for i in range(N)):
            continue

        x_ddt_profiles = {}
        for d in range(1, 256):
            x_ddt_profiles[d] = ddt_row_profile(x_perm, d)

        # Step 3: Backtracking search for B columns
        B_cols = [None] * N

        def check_consistency(col_idx):
            for i in range(col_idx):
                d_input = (1 << i) ^ (1 << col_idx)
                d_output = B_cols[i] ^ B_cols[col_idx]
                if d_output == 0:
                    return False
                if s_profiles[d_input] != x_ddt_profiles.get(d_output, None):
                    return False
            return True

        def backtrack(col_idx):
            if col_idx == N:
                B_mat = [[0] * N for _ in range(N)]
                for col in range(N):
                    for row in range(N):
                        B_mat[row][col] = (B_cols[col] >> row) & 1
                B_inv = mat_inv_gf2(B_mat)
                if B_inv is None:
                    return None

                A_table = [None] * 256
                for x in range(256):
                    bx = 0
                    for i in range(N):
                        if (x >> i) & 1:
                            bx ^= B_cols[i]
                    z = x_perm[bx]
                    if A_table[z] is not None and A_table[z] != sbox[x]:
                        return None
                    A_table[z] = sbox[x]

                if any(v is None for v in A_table):
                    return None

                if A_table[0] != 0:
                    return None
                for i in range(N):
                    for j in range(i + 1, N):
                        if A_table[(1 << i) ^ (1 << j)] != (
                            A_table[1 << i] ^ A_table[1 << j]
                        ):
                            return None

                A_mat = [[0] * N for _ in range(N)]
                for col in range(N):
                    for row in range(N):
                        A_mat[row][col] = (A_table[1 << col] >> row) & 1

                return A_mat, B_mat

            for c in col_candidates[col_idx]:
                B_cols[col_idx] = c
                if check_consistency(col_idx):
                    result = backtrack(col_idx + 1)
                    if result is not None:
                        return result
            B_cols[col_idx] = None
            return None

        result = backtrack(0)
        if result is not None:
            A_mat, B_mat = result

            ok = True
            for x in range(256):
                v = int_to_bits(x)
                w = mat_vec_gf2(B_mat, v)
                y = bits_to_int(w)
                z = (a_val * y + b_val) % 256
                u = int_to_bits(z)
                t = mat_vec_gf2(A_mat, u)
                sx = bits_to_int(t)
                if sx != sbox[x]:
                    ok = False
                    break

            if ok:
                return {
                    "A": A_mat,
                    "B": B_mat,
                    "a": a_val,
                    "b": b_val,
                }

    return None


def main():
    obj_path = "/app/cipher_impl/sbox.o"

    # Step 1: Extract S-boxes from the ELF object file
    print("Extracting S-box tables from ELF object file...", file=sys.stderr)
    sbox_tables = extract_sboxes_from_elf(obj_path)

    if len(sbox_tables) != 4:
        print(f"ERROR: Expected 4 S-box tables, found {len(sbox_tables)}",
              file=sys.stderr)
        sys.exit(1)

    for tid, table in sbox_tables.items():
        assert len(table) == 256, f"Table T{tid} has {len(table)} entries"
        assert len(set(table)) == 256, f"Table T{tid} is not a permutation"

    # Step 2: Identify the weak S-box
    print("Analyzing algebraic properties...", file=sys.stderr)
    weak_id = identify_weak_sbox(sbox_tables)
    print(f"Identified weak S-box: T{weak_id}", file=sys.stderr)

    # Step 3: Decompose the weak S-box
    print("Recovering decomposition...", file=sys.stderr)
    weak_sbox = sbox_tables[weak_id]
    decomposition = decompose_sbox(weak_sbox)

    if decomposition is None:
        print("ERROR: Could not find a valid decomposition", file=sys.stderr)
        sys.exit(1)

    findings = {
        "weak_sbox_id": weak_id,
        "decomposition": decomposition,
    }

    with open("/app/findings.json", "w") as f:
        json.dump(findings, f, indent=2)

    print(f"Findings written to /app/findings.json", file=sys.stderr)
    print(f"  weak_sbox_id: {weak_id}", file=sys.stderr)
    print(f"  a={decomposition['a']}, b={decomposition['b']}", file=sys.stderr)


if __name__ == "__main__":
    main()
