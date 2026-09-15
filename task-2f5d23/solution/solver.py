#!/usr/bin/env python3
"""CRC Polynomial HD Profile Analyzer with C Library Pipeline.

Generates table-driven CRC-8 C code for each polynomial, compiles to
shared libraries via gcc, loads them with ctypes, and cross-validates
against pure Python GF(2) LFSR computation.

"""

import json
import os
import subprocess
import ctypes
import bisect
from itertools import combinations
from collections import Counter, defaultdict


# ---------------------------------------------------------------------------
# Koopman notation conversion
# ---------------------------------------------------------------------------

def koopman_to_explicit(koopman_hex, n_bits):
    k = int(koopman_hex, 16)
    return (k << 1) | 1


def koopman_to_poly_lower(koopman_hex, n_bits):
    explicit = koopman_to_explicit(koopman_hex, n_bits)
    return explicit & ((1 << n_bits) - 1)


# ---------------------------------------------------------------------------
# C code generation, compilation, and ctypes loading
# ---------------------------------------------------------------------------

def build_crc_table(poly_lower):
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ poly_lower) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
        table.append(crc)
    return table


def generate_c_source(poly_lower, init, xor_out):
    table = build_crc_table(poly_lower)
    rows = []
    for r in range(16):
        entries = ", ".join(f"0x{table[r*16+c]:02x}" for c in range(16))
        rows.append(f"    {entries}")
    table_str = ",\n".join(rows)

    return (
        f"static const unsigned char crc_table[256] = {{\n"
        f"{table_str}\n"
        f"}};\n"
        f"\n"
        f"unsigned char crc8_compute(const unsigned char *data, unsigned int len) {{\n"
        f"    unsigned char crc = 0x{init:02x};\n"
        f"    unsigned int i;\n"
        f"    for (i = 0; i < len; i++) {{\n"
        f"        crc = crc_table[crc ^ data[i]];\n"
        f"    }}\n"
        f"    return crc ^ 0x{xor_out:02x};\n"
        f"}}\n"
    )


def compile_and_load_libraries(polynomials, n_bits, init, xor_out, lib_dir, tmp_dir):
    os.makedirs(lib_dir, exist_ok=True)
    os.makedirs(tmp_dir, exist_ok=True)
    libraries = {}

    for poly_hex in polynomials:
        poly_lower = koopman_to_poly_lower(poly_hex, n_bits)
        c_src = generate_c_source(poly_lower, init, xor_out)

        c_path = os.path.join(tmp_dir, f"crc_{poly_hex}.c")
        so_path = os.path.join(lib_dir, f"crc_{poly_hex}.so")

        with open(c_path, "w") as f:
            f.write(c_src)

        result = subprocess.run(
            ["gcc", "-shared", "-fPIC", "-O2", "-o", so_path, c_path],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"gcc failed for {poly_hex}: {result.stderr}")

        lib = ctypes.CDLL(so_path)
        lib.crc8_compute.argtypes = [ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint]
        lib.crc8_compute.restype = ctypes.c_ubyte
        libraries[poly_hex] = lib
        print(f"  Compiled and loaded {so_path}")

    return libraries


def compute_crc_ctypes(lib, data):
    buf = (ctypes.c_ubyte * len(data))(*data)
    return lib.crc8_compute(buf, len(data))


# ---------------------------------------------------------------------------
# Pure Python CRC (for cross-validation)
# ---------------------------------------------------------------------------

def compute_crc_python(data, poly_lower, init=0, xor_out=0):
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ poly_lower) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc ^ xor_out


# ---------------------------------------------------------------------------
# GF(2) syndrome computation and HD profile analysis
# ---------------------------------------------------------------------------

def compute_syndromes(explicit_poly, n_bits, codeword_length):
    syndromes = []
    s = 1
    for i in range(codeword_length):
        syndromes.append(s)
        s <<= 1
        if s & (1 << n_bits):
            s ^= explicit_poly
    return syndromes


def has_x_plus_1_factor(explicit_poly):
    return bin(explicit_poly).count('1') % 2 == 0


def check_hw_zero(syndromes, weight):
    n = len(syndromes)
    if weight == 2:
        return len(set(syndromes)) == n
    if weight == 3:
        syn_set = set(syndromes)
        for i in range(n):
            for j in range(i + 1, n):
                xor_val = syndromes[i] ^ syndromes[j]
                if xor_val != 0 and xor_val in syn_set:
                    return False
        return True
    if weight == 4:
        pair_xors = defaultdict(list)
        for i in range(n):
            for j in range(i + 1, n):
                xor_val = syndromes[i] ^ syndromes[j]
                pair_xors[xor_val].append((i, j))
        for xor_val, pairs in pair_xors.items():
            if len(pairs) >= 2:
                for p1 in range(len(pairs)):
                    for p2 in range(p1 + 1, len(pairs)):
                        a, b = pairs[p1]
                        c, d = pairs[p2]
                        if len({a, b, c, d}) == 4:
                            return False
        return True
    for combo in combinations(range(n), weight):
        xor_val = 0
        for idx in combo:
            xor_val ^= syndromes[idx]
        if xor_val == 0:
            return False
    return True


def compute_hamming_weight(syndromes, weight):
    n = len(syndromes)
    if weight == 2:
        c = Counter(syndromes)
        return sum(v * (v - 1) // 2 for v in c.values())
    if weight == 3:
        pos_by_syn = defaultdict(list)
        for idx, s in enumerate(syndromes):
            pos_by_syn[s].append(idx)
        count = 0
        for i in range(n):
            for j in range(i + 1, n):
                target = syndromes[i] ^ syndromes[j]
                if target == 0:
                    continue
                positions = pos_by_syn.get(target, [])
                count += len(positions) - bisect.bisect_right(positions, j)
        return count
    count = 0
    for combo in combinations(range(n), weight):
        xor_val = 0
        for idx in combo:
            xor_val ^= syndromes[idx]
        if xor_val == 0:
            count += 1
    return count


def compute_hd_profile(koopman_hex, n_bits, max_dataword_length):
    explicit = koopman_to_explicit(koopman_hex, n_bits)
    max_cw = max_dataword_length + n_bits
    all_syndromes = compute_syndromes(explicit, n_bits, max_cw)

    profile = []
    prev_boundary = max_dataword_length
    gen_weight = bin(explicit).count('1')

    for hd_level in range(3, gen_weight + 1):
        check_weight = hd_level - 1
        lo, hi = 1, prev_boundary
        boundary = 0
        while lo <= hi:
            mid = (lo + hi) // 2
            cw = mid + n_bits
            if check_hw_zero(all_syndromes[:cw], check_weight):
                boundary = mid
                lo = mid + 1
            else:
                hi = mid - 1
        if boundary == 0:
            break
        profile.append(boundary)
        prev_boundary = boundary

    return profile


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    with open('/app/config.json') as f:
        config = json.load(f)

    n_bits = config['crc_bits']
    max_len = config['max_dataword_length_bits']
    polynomials = config['polynomials_koopman_hex']
    hw_queries = config['hamming_weight_queries']
    crc_params = config['crc_params']
    init = int(crc_params['init'], 16)
    xor_out = int(crc_params['xor_out'], 16)

    # Step 1: Generate C code, compile shared libraries, load via ctypes
    print("Building C shared libraries...")
    libraries = compile_and_load_libraries(
        polynomials, n_bits, init, xor_out,
        lib_dir="/app/lib", tmp_dir="/tmp/crc_build"
    )

    # Step 2: Read test data files
    testdata_dir = "/app/testdata"
    test_files = {}
    for fname in sorted(os.listdir(testdata_dir)):
        fpath = os.path.join(testdata_dir, fname)
        if os.path.isfile(fpath):
            with open(fpath, "rb") as f:
                test_files[fname] = f.read()

    # Step 3: Compute CRCs via C libraries (ctypes)
    print("Computing CRC checksums via C libraries...")
    checksums = {}
    for fname, data in test_files.items():
        checksums[fname] = {}
        for poly_hex in polynomials:
            crc_val = compute_crc_ctypes(libraries[poly_hex], data)
            checksums[fname][poly_hex] = crc_val

    # Step 4: Cross-validate with pure Python implementation
    print("Cross-validating with Python GF(2) LFSR...")
    cross_validation_passed = True
    for fname, data in test_files.items():
        for poly_hex in polynomials:
            poly_lower = koopman_to_poly_lower(poly_hex, n_bits)
            py_crc = compute_crc_python(data, poly_lower, init, xor_out)
            c_crc = checksums[fname][poly_hex]
            if py_crc != c_crc:
                print(f"  MISMATCH: {fname}/{poly_hex}: C={c_crc}, Python={py_crc}")
                cross_validation_passed = False
            else:
                print(f"  OK: {fname}/{poly_hex} = 0x{c_crc:02x}")

    # Step 5: Compute HD profiles and (x+1) factor
    print("Computing HD profiles...")
    profiles = {}
    for poly_hex in polynomials:
        explicit = koopman_to_explicit(poly_hex, n_bits)
        profile = compute_hd_profile(poly_hex, n_bits, max_len)
        has_factor = has_x_plus_1_factor(explicit)
        profiles[poly_hex] = {
            'hd_profile': profile,
            'has_x_plus_1_factor': has_factor
        }
        print(f"  {poly_hex}: profile={profile}, (x+1)={has_factor}")

    # Step 6: Compute Hamming weight queries
    print("Computing Hamming weight queries...")
    hamming_weights = []
    for query in hw_queries:
        poly_hex = query['polynomial']
        dw_len = query['dataword_length']
        weight = query['error_weight']
        explicit = koopman_to_explicit(poly_hex, n_bits)
        cw_len = dw_len + n_bits
        syns = compute_syndromes(explicit, n_bits, cw_len)
        hw = compute_hamming_weight(syns, weight)
        hamming_weights.append({
            'polynomial': poly_hex,
            'dataword_length': dw_len,
            'error_weight': weight,
            'hw_value': hw
        })
        print(f"  HW({weight}) at {poly_hex} L={dw_len}: {hw}")

    # Step 7: Write results
    results = {
        'profiles': profiles,
        'checksums': checksums,
        'cross_validation_passed': cross_validation_passed,
        'hamming_weights': hamming_weights
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == '__main__':
    main()
