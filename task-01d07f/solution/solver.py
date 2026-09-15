"""
STRIX-8 S-Box Structural Analysis Solver

Extracts the S-box from cipher.so, queries the analysis database for
construction hints, discovers the triangular/staircase structure via
algebraic degree analysis, and decomposes S = A . X . B.
"""

import ctypes
import json
import sqlite3
import subprocess


# ---- Step 1: Binary analysis & S-box extraction ----

def extract_sbox():
    """Extract the 8-bit S-box from cipher.so using binary analysis tools."""
    print("=== Step 1: Binary analysis and S-box extraction ===")

    # Examine the shared library structure
    print("-- Examining ELF sections --")
    result = subprocess.run(
        ["readelf", "-S", "/app/cipher.so"],
        capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        if ".rodata" in line or "Section" in line or "Name" in line:
            print(f"  {line.strip()}")

    # List dynamic symbols to find S-box access functions
    print("\n-- Dynamic symbols --")
    result = subprocess.run(
        ["nm", "-D", "/app/cipher.so"],
        capture_output=True, text=True,
    )
    print(result.stdout.strip())

    # Use ctypes to call strix_sub and recover the full lookup table
    print("\n-- Extracting S-box via ctypes --")
    lib = ctypes.CDLL("/app/cipher.so")
    lib.strix_sub.restype = ctypes.c_uint8
    lib.strix_sub.argtypes = [ctypes.c_uint8]

    sbox = [lib.strix_sub(i) for i in range(256)]
    assert len(set(sbox)) == 256, "Not a permutation!"
    print(f"  S-box extracted: {sbox[:16]}... (256 values, bijective)")
    return sbox


# ---- Step 2: Database investigation ----

def query_database():
    """Query analysis.db for construction hints and partial results."""
    print("\n=== Step 2: Querying analysis database ===")

    conn = sqlite3.connect("/app/analysis.db")
    c = conn.cursor()

    c.execute("SELECT value FROM cipher_metadata WHERE key='construction_method'")
    print(f"Construction: {c.fetchone()[0]}")

    c.execute("SELECT value FROM cipher_metadata WHERE key='design_rationale'")
    print(f"Rationale: {c.fetchone()[0]}")

    c.execute(
        "SELECT timestamp, note FROM analysis_log "
        "WHERE category IN ('reference','structural') ORDER BY id"
    )
    for ts, note in c.fetchall():
        print(f"  [{ts}] {note[:120]}...")

    c.execute(
        "SELECT mask, algebraic_degree FROM degree_analysis "
        "WHERE notes != '' ORDER BY mask"
    )
    anomalous = c.fetchall()
    print(f"\nAnomalous-degree components in DB: {len(anomalous)}")
    for mask, deg in anomalous[:10]:
        print(f"  mask={mask:3d} (0x{mask:02x}): degree {deg}")

    conn.close()
    print("\n  => Construction is modular arithmetic mod 256.")
    print("  => Literature reference: triangular/T-function structure.")
    print("  => Bit i of output depends only on bits 0..i of input.")
    print("  => The nonlinear core X must be TRIANGULAR.")


# ---- Utility functions ----

def int_to_bits(x, n=8):
    return [(x >> (n - 1 - i)) & 1 for i in range(n)]


def bits_to_int(bits):
    val = 0
    for b in bits:
        val = (val << 1) | b
    return val


def compute_anf(truth_table):
    anf = truth_table[:]
    for i in range(8):
        step = 1 << i
        for j in range(256):
            if j & step:
                anf[j] ^= anf[j ^ step]
    return anf


def anf_degree(anf):
    max_deg = 0
    for idx in range(len(anf)):
        if anf[idx]:
            deg = bin(idx).count("1")
            if deg > max_deg:
                max_deg = deg
    return max_deg


def component_degree(sbox, mask):
    tt = []
    for x in range(256):
        val = sbox[x] & mask
        parity = bin(val).count("1") % 2
        tt.append(parity)
    anf = compute_anf(tt)
    return anf_degree(anf)


def mat_inverse_gf2(M):
    n = 8
    aug = [M[i][:] + [1 if j == i else 0 for j in range(n)] for i in range(n)]
    for col in range(n):
        pivot = -1
        for row in range(col, n):
            if aug[row][col] == 1:
                pivot = row
                break
        if pivot == -1:
            raise ValueError("Matrix is not invertible")
        if pivot != col:
            aug[col], aug[pivot] = aug[pivot], aug[col]
        for row in range(n):
            if row != col and aug[row][col] == 1:
                for j in range(2 * n):
                    aug[row][j] ^= aug[col][j]
    return [aug[i][n:] for i in range(n)]


def mat_vec_gf2(M, v):
    result = []
    for i in range(8):
        bit = 0
        for j in range(8):
            bit ^= M[i][j] & v[j]
        result.append(bit)
    return result


def apply_linear(mat, x):
    x_bits = int_to_bits(x)
    result = mat_vec_gf2(mat, x_bits)
    return bits_to_int(result)


def extract_basis(masks_set):
    basis = []
    span = {0}
    for m in sorted(masks_set):
        if m not in span:
            basis.append(m)
            new_span = set()
            for s in span:
                new_span.add(s ^ m)
            span.update(new_span)
    return basis


def is_triangular(table):
    for k in range(1, 9):
        mod = 1 << k
        for r in range(mod):
            vals = set()
            for x in range(r, 256, mod):
                vals.add(table[x] % mod)
            if len(vals) > 1:
                return False
    return True


# ---- Step 3: Recover A^{-1} from degree analysis ----

def recover_A_inv(sbox):
    """Recover the inverse of the outer affine map from the degree
    stratification of component Boolean functions."""
    print("\n=== Step 3: Recovering A^{-1} via degree analysis ===")

    mask_degrees = {}
    for mask in range(1, 256):
        mask_degrees[mask] = component_degree(sbox, mask)

    degree_groups = {}
    for mask, deg in mask_degrees.items():
        if deg not in degree_groups:
            degree_groups[deg] = []
        degree_groups[deg].append(mask)

    print("  Degree distribution:")
    for d in sorted(degree_groups):
        print(f"    degree {d}: {len(degree_groups[d])} masks")

    max_deg = max(degree_groups.keys())
    cumulative_masks = set()
    prev_span = {0}
    level_vectors = []

    for d in range(1, max_deg + 1):
        if d in degree_groups:
            cumulative_masks.update(degree_groups[d])
        current_basis = extract_basis(cumulative_masks)
        new_vecs = []
        for v in current_basis:
            if v not in prev_span:
                new_vecs.append(v)
                new_span = set()
                for s in prev_span:
                    new_span.add(s ^ v)
                prev_span.update(new_span)
        if new_vecs:
            level_vectors.append((d, new_vecs))

    ordered_rows = []
    for d, vecs in reversed(level_vectors):
        for v in vecs:
            ordered_rows.append(v)

    assert len(ordered_rows) == 8, f"Expected 8 rows, got {len(ordered_rows)}"
    print(f"  A_inv rows (as ints): {ordered_rows}")
    return [int_to_bits(m) for m in ordered_rows]


# ---- Step 4: Recover B from triangular kernel analysis ----

def compute_kernel(T, k):
    """ker_k = {delta : T(x ^ delta) mod 2^k = T(x) mod 2^k for all x}"""
    mod = 1 << k
    kernel = set(range(256))
    for x in range(256):
        t_x = T[x] % mod
        to_remove = {delta for delta in kernel if T[x ^ delta] % mod != t_x}
        kernel -= to_remove
        if len(kernel) <= 1:
            break
    return kernel


def compute_annihilator(kernel_set):
    """Compute ann(V) = {v : v . w = 0 for all w in V}."""
    nonzero = kernel_set - {0}
    if not nonzero:
        return set(range(256))

    basis = extract_basis(nonzero)
    n = 8
    m = len(basis)
    M = [int_to_bits(b) for b in basis]

    M_red = [row[:] for row in M]
    pivots = []
    col = 0
    for row_idx in range(m):
        while col < n:
            piv = -1
            for r in range(row_idx, m):
                if M_red[r][col] == 1:
                    piv = r
                    break
            if piv == -1:
                col += 1
                continue
            M_red[row_idx], M_red[piv] = M_red[piv], M_red[row_idx]
            for r in range(m):
                if r != row_idx and M_red[r][col] == 1:
                    for c in range(n):
                        M_red[r][c] ^= M_red[row_idx][c]
            pivots.append(col)
            col += 1
            break

    pivot_set = set(pivots)
    free_vars = [j for j in range(n) if j not in pivot_set]

    null_basis = []
    for fv in free_vars:
        v = [0] * n
        v[fv] = 1
        for idx, pv in enumerate(pivots):
            v[pv] = M_red[idx][fv]
        null_basis.append(bits_to_int(v))

    ann = {0}
    for nb in null_basis:
        new_ann = set()
        for a in ann:
            new_ann.add(a ^ nb)
        ann.update(new_ann)
    return ann


def recover_B_from_T(T):
    """Recover B_mat from T using kernel and annihilator analysis,
    exploiting the triangular structure of X."""
    print("\n=== Step 4: Recovering B via triangular kernel analysis ===")

    kernels = [set(range(256))]
    anns = [{0}]

    for k in range(1, 9):
        ker = compute_kernel(T, k)
        ann = compute_annihilator(ker)
        kernels.append(ker)
        anns.append(ann)
        ker_dim = len(ker).bit_length() - 1
        ann_dim = len(ann).bit_length() - 1
        print(f"  k={k}: |ker|={len(ker)} (dim ~{ker_dim}), "
              f"|ann|={len(ann)} (dim ~{ann_dim})")

    B_rows = [None] * 8
    used_span = {0}

    for k in range(1, 9):
        row_idx = 8 - k
        candidates = anns[k] - anns[k - 1]
        chosen = None
        for v in sorted(candidates):
            if v not in used_span:
                chosen = v
                break
        assert chosen is not None, f"No valid vector for B row {row_idx}"
        B_rows[row_idx] = int_to_bits(chosen)
        new_span = set()
        for s in used_span:
            new_span.add(s ^ chosen)
        used_span.update(new_span)
        print(f"  B row {row_idx}: {chosen} (0x{chosen:02x})")

    return B_rows


# ---- Main solver ----

def main():
    # Step 1: Extract S-box from compiled library
    sbox = extract_sbox()

    # Step 2: Query database for construction hints
    query_database()

    # Step 3: Recover A via degree analysis
    A_inv = recover_A_inv(sbox)
    A_mat = mat_inverse_gf2(A_inv)

    # Compute T = A^{-1} * S
    print("\n  Computing T = A^{-1} . S ...")
    T = [apply_linear(A_inv, sbox[x]) for x in range(256)]
    assert len(set(T)) == 256

    # Step 4: Recover B via triangular kernel analysis
    B_rows = recover_B_from_T(T)
    B_mat = B_rows
    B_mat_inv = mat_inverse_gf2(B_mat)

    # Step 5: Compute X and verify triangularity
    print("\n=== Step 5: Computing X and verifying ===")
    X_table = [T[apply_linear(B_mat_inv, x)] for x in range(256)]
    assert len(set(X_table)) == 256, "X is not a permutation"

    tri = is_triangular(X_table)
    print(f"  X is triangular: {tri}")
    assert tri, "X is not triangular - decomposition failed"

    # Verify full decomposition
    A_const = [0] * 8
    B_const = [0] * 8
    for x in range(256):
        bx = apply_linear(B_mat, x)
        xx = X_table[bx]
        sx = apply_linear(A_mat, xx)
        assert sx == sbox[x], f"Verification failed at x={x}"
    print("  Decomposition verified for all 256 inputs.")

    # Write answer
    answer = {
        "A_mat": [list(row) for row in A_mat],
        "A_const": list(A_const),
        "B_mat": [list(row) for row in B_mat],
        "B_const": list(B_const),
        "X_table": list(X_table),
    }
    with open("/app/answer.json", "w") as f:
        json.dump(answer, f, indent=2)
    print("\nAnswer written to /app/answer.json")


if __name__ == "__main__":
    main()
