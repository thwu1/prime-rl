#!/usr/bin/env python3
"""
Extract S-box from compiled shared library, decompose into affine-arithmetic form.

Steps:
1. Query cipher.db to find the target symbol name
2. Use readelf/nm to locate the symbol in the ELF binary, then extract bytes
3. Run algebraic decomposition (ANF, staircase filtration, tree search)
4. Write answer.json

"""

import ctypes
import json
import os
import re
import sqlite3
import subprocess
import sys


# ─── Step 1: Query the database ────────────────────────────────────────────

def query_target_symbol():
    """Query cipher.db to find which symbol is the target S-box."""
    conn = sqlite3.connect("/app/cipher.db")
    c = conn.cursor()
    c.execute("SELECT value FROM cipher_metadata WHERE param='target_component'")
    row = c.fetchone()
    if row is None:
        raise RuntimeError("target_component not found in cipher_metadata")
    symbol_name = row[0]
    # Cross-reference with library_symbols
    c.execute("SELECT description, element_count FROM library_symbols WHERE symbol_name=?",
              (symbol_name,))
    info = c.fetchone()
    conn.close()
    print(f"Target symbol: {symbol_name}")
    if info:
        print(f"  Description: {info[0]}, Elements: {info[1]}")
    return symbol_name


# ─── Step 2: Extract S-box from the binary ─────────────────────────────────

def extract_sbox_readelf(symbol_name):
    """Extract 256-byte S-box from the ELF shared library using readelf + binary read."""
    # Find symbol virtual address and size
    output = subprocess.check_output(
        ["readelf", "-s", "--wide", "/app/libcipher.so"], text=True
    )
    sym_addr = None
    sym_size = None
    for line in output.strip().split("\n"):
        if symbol_name in line:
            parts = line.split()
            # readelf -s format: Num Value Size Type Bind Vis Ndx Name
            for i, p in enumerate(parts):
                if p == symbol_name:
                    sym_addr = int(parts[1], 16)
                    sym_size = int(parts[2])
                    break
            if sym_addr is not None:
                break

    if sym_addr is None:
        raise RuntimeError(f"Symbol {symbol_name} not found via readelf -s")
    print(f"  Symbol address: 0x{sym_addr:x}, size: {sym_size}")

    # Find the section containing this address to compute file offset
    sections_output = subprocess.check_output(
        ["readelf", "-S", "--wide", "/app/libcipher.so"], text=True
    )
    best_section = None
    best_vaddr = 0
    best_offset = 0
    for line in sections_output.strip().split("\n"):
        # Match section lines: [Nr] Name Type Address Offset Size ...
        m = re.search(r'\[\s*\d+\]\s+(\S+)\s+\S+\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)', line)
        if m:
            sec_name = m.group(1)
            sec_vaddr = int(m.group(2), 16)
            sec_offset = int(m.group(3), 16)
            sec_size = int(m.group(4), 16)
            if sec_vaddr <= sym_addr < sec_vaddr + sec_size:
                if sec_vaddr >= best_vaddr:
                    best_section = sec_name
                    best_vaddr = sec_vaddr
                    best_offset = sec_offset

    if best_section is None:
        raise RuntimeError("Could not find section containing the symbol")

    file_offset = best_offset + (sym_addr - best_vaddr)
    print(f"  Section: {best_section}, file offset: 0x{file_offset:x}")

    with open("/app/libcipher.so", "rb") as f:
        f.seek(file_offset)
        data = f.read(256)

    return list(data)


def extract_sbox_ctypes(symbol_name):
    """Fallback: extract S-box using ctypes in_dll."""
    lib = ctypes.CDLL("/app/libcipher.so")
    sbox_arr = (ctypes.c_uint8 * 256).in_dll(lib, symbol_name)
    return list(sbox_arr)


def extract_sbox(symbol_name):
    """Extract the S-box, trying readelf first then ctypes fallback."""
    try:
        sbox = extract_sbox_readelf(symbol_name)
        print(f"  Extracted via readelf: first 16 bytes = {sbox[:16]}")
        return sbox
    except Exception as e:
        print(f"  readelf extraction failed ({e}), falling back to ctypes")
        sbox = extract_sbox_ctypes(symbol_name)
        print(f"  Extracted via ctypes: first 16 bytes = {sbox[:16]}")
        return sbox


# ─── Step 3: Algebraic decomposition ──────────────────────────────────────

def int_to_bits(n, width=8):
    return [(n >> i) & 1 for i in range(width)]


def bits_to_int(bits):
    return sum(b << i for i, b in enumerate(bits))


def mat_mul_gf2_vec(M, v):
    n = len(M)
    result = [0] * n
    for i in range(n):
        s = 0
        for j in range(n):
            s ^= M[i][j] & v[j]
        result[i] = s
    return result


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
    return [row[n:] for row in aug]


def apply_linear_map(M, x):
    x_bits = int_to_bits(x, 8)
    result_bits = mat_mul_gf2_vec(M, x_bits)
    return bits_to_int(result_bits)


def compute_anf(tt, n=8):
    anf = list(tt)
    for i in range(n):
        for j in range(1 << n):
            if j & (1 << i):
                anf[j] ^= anf[j ^ (1 << i)]
    return anf


def algebraic_degree(anf):
    max_deg = 0
    for i in range(len(anf)):
        if anf[i]:
            deg = bin(i).count('1')
            if deg > max_deg:
                max_deg = deg
    return max_deg


def extended_gcd(a, b):
    if a == 0:
        return b, 0, 1
    g, x, y = extended_gcd(b % a, a)
    return g, y - (b // a) * x, x


def modinv(a, m):
    g, x, _ = extended_gcd(a % m, m)
    if g != 1:
        return None
    return x % m


def gf2_span(vectors, n=8):
    if not vectors:
        return set()
    span = {0}
    for v in vectors:
        new_span = set(span)
        for s in span:
            new_span.add(s ^ v)
        span = new_span
    span.discard(0)
    return span


def is_gf2_independent(chosen, new_v, n=8):
    all_span = gf2_span(chosen, n)
    return new_v not in all_span and new_v != 0


def gen_independent_triples(vectors):
    n = len(vectors)
    for i in range(n):
        for j in range(n):
            if j == i:
                continue
            if vectors[i] ^ vectors[j] == 0:
                continue
            for k in range(n):
                if k == i or k == j:
                    continue
                a, b, c = vectors[i], vectors[j], vectors[k]
                if a ^ b == c or a ^ c == b or b ^ c == a:
                    continue
                if a ^ b ^ c == 0:
                    continue
                yield (a, b, c)


def compute_partial_fB(sbox, rows):
    k = len(rows)
    partial_fB = []
    for x in range(256):
        val = 0
        sx = sbox[x]
        for i, v in enumerate(rows):
            bit = 0
            for j in range(8):
                if (v >> j) & 1:
                    bit ^= (sx >> j) & 1
            val |= (bit << i)
        partial_fB.append(val)
    return partial_fB


def check_partial_arithmetic(partial_fB, k):
    mod = 1 << k
    b_partial = partial_fB[0] % mod
    g = [(partial_fB[x] - b_partial) % mod for x in range(256)]

    for a_cand in range(1, mod, 2):
        a_inv_m = modinv(a_cand, mod)
        if a_inv_m is None:
            continue
        h = [(g[x] * a_inv_m) % mod for x in range(256)]
        if h[0] != 0:
            continue
        ok = True
        for i in range(8):
            if not ok:
                break
            for j in range(i + 1, 8):
                if h[(1 << i) ^ (1 << j)] != (h[1 << i] ^ h[1 << j]):
                    ok = False
                    break
        if not ok:
            continue
        valid = True
        for x in range(256):
            expected = 0
            for i in range(8):
                if (x >> i) & 1:
                    expected ^= h[1 << i]
            if h[x] != expected:
                valid = False
                break
        if valid:
            return True
    return False


def try_full_decompose(sbox, rows):
    a_inv_matrix = [int_to_bits(v, 8) for v in rows]
    A_inv_mat = mat_inv_gf2(a_inv_matrix)
    if A_inv_mat is None:
        return None

    fB = compute_partial_fB(sbox, rows)
    b_val = fB[0]
    g = [(fB[x] - b_val) % 256 for x in range(256)]

    for a_cand in range(1, 256, 2):
        a_inv_m = modinv(a_cand, 256)
        if a_inv_m is None:
            continue
        h = [(g[x] * a_inv_m) % 256 for x in range(256)]
        if h[0] != 0:
            continue
        ok = True
        for i in range(8):
            if not ok:
                break
            for j in range(i + 1, 8):
                if h[(1 << i) ^ (1 << j)] != (h[1 << i] ^ h[1 << j]):
                    ok = False
                    break
        if not ok:
            continue
        valid = True
        for x in range(256):
            expected = 0
            for i in range(8):
                if (x >> i) & 1:
                    expected ^= h[1 << i]
            if h[x] != expected:
                valid = False
                break
        if not valid:
            continue

        B_matrix = [[0] * 8 for _ in range(8)]
        for col in range(8):
            col_val = h[1 << col]
            col_bits = int_to_bits(col_val, 8)
            for row in range(8):
                B_matrix[row][col] = col_bits[row]

        if mat_inv_gf2(B_matrix) is None:
            continue

        A_matrix = mat_inv_gf2(a_inv_matrix)

        all_ok = True
        for x in range(256):
            bx = apply_linear_map(B_matrix, x)
            fx = (a_cand * bx + b_val) % 256
            sx = apply_linear_map(A_matrix, fx)
            if sx != sbox[x]:
                all_ok = False
                break
        if all_ok:
            return (a_cand, b_val, A_matrix, B_matrix)

    return None


def solve():
    # Step 1: Query the database
    symbol_name = query_target_symbol()

    # Step 2: Extract the S-box from the binary
    sbox = extract_sbox(symbol_name)
    assert len(sbox) == 256 and len(set(sbox)) == 256, "Invalid S-box"

    # Step 3: Algebraic decomposition
    output_tts = []
    for bit in range(8):
        tt = [(sbox[x] >> bit) & 1 for x in range(256)]
        output_tts.append(tt)

    degrees = {}
    for v in range(1, 256):
        tt = [0] * 256
        for bit in range(8):
            if (v >> bit) & 1:
                tt = [tt[x] ^ output_tts[bit][x] for x in range(256)]
        anf = compute_anf(tt)
        degrees[v] = algebraic_degree(anf)

    filtration = {}
    for k in range(1, 8):
        filtration[k] = sorted([v for v in range(1, 256) if degrees[v] <= k])

    for k in range(1, 8):
        basis = []
        for v in filtration[k]:
            if is_gf2_independent(basis, v):
                basis.append(v)
        print(f"V_{k}: rank={len(basis)}, |vectors|={len(filtration[k])}")

    v1_vectors = filtration[1]
    v1_basis = []
    for v in v1_vectors:
        if is_gf2_independent(v1_basis, v):
            v1_basis.append(v)
    v1_all = sorted(gf2_span(v1_basis))

    print(f"V_1 rank: {len(v1_basis)}, all nonzero: {v1_all}")

    extend_levels = []
    current_rank = len(v1_basis)
    for k in range(2, 8):
        basis_k = []
        for v in filtration[k]:
            if is_gf2_independent(basis_k, v):
                basis_k.append(v)
        rank_k = len(basis_k)
        while current_rank < rank_k:
            extend_levels.append(k)
            current_rank += 1
    print(f"Extension levels: {extend_levels}")

    def get_candidates(rows, level):
        candidates = []
        for v in filtration[level]:
            if is_gf2_independent(rows, v):
                candidates.append(v)
        return candidates

    count = [0]

    def search(rows, level_idx):
        count[0] += 1
        if count[0] % 10000 == 0:
            print(f"  Search steps: {count[0]}, rows={len(rows)}")

        if len(rows) == 8:
            return try_full_decompose(sbox, rows)

        level = extend_levels[level_idx]
        candidates = get_candidates(rows, level)

        for v in candidates:
            rows.append(v)
            k = len(rows)
            partial_fB = compute_partial_fB(sbox, rows)
            if check_partial_arithmetic(partial_fB, k):
                result = search(rows, level_idx + 1)
                if result is not None:
                    return result
            rows.pop()

        return None

    ordered_bases = list(gen_independent_triples(v1_all))
    print(f"Number of ordered V_1 bases: {len(ordered_bases)}")

    for idx, base in enumerate(ordered_bases):
        if idx % 20 == 0:
            print(f"Trying V_1 basis {idx}/{len(ordered_bases)}: {base}")
        rows = list(base)
        partial_fB_3 = compute_partial_fB(sbox, rows)
        if not check_partial_arithmetic(partial_fB_3, 3):
            continue
        result = search(rows, 0)
        if result is not None:
            a_val, b_val, A_mat, B_mat = result
            print(f"\nFound decomposition!")
            print(f"a = {a_val}, b = {b_val}")
            answer = {
                "a": a_val,
                "b": b_val,
                "A": A_mat,
                "B": B_mat,
            }
            with open('/app/answer.json', 'w') as f:
                json.dump(answer, f, indent=2)
            print("Answer written to /app/answer.json")
            return

    print("ERROR: No valid decomposition found!")
    sys.exit(1)


if __name__ == '__main__':
    solve()
