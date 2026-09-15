#!/usr/bin/env python3

"""
CRC-8 Polynomial Error Detection Analysis — Solution

Parses binary test data, compiles and uses the C CRC engine for cross-validation,
performs GF(2) polynomial factorization via sympy, computes Hamming Distance bounds,
and writes consolidated results to /app/results.json.
"""

import json
import os
import struct
import subprocess

from sympy import symbols, Poly, GF

x = symbols('x')


def parse_test_data(filepath):
    """Parse the custom binary test data format described in FORMAT.md."""
    vectors = {}
    with open(filepath, 'rb') as f:
        magic = f.read(4)
        assert magic == b"CRC8", f"Bad magic: {magic}"
        version = struct.unpack('B', f.read(1))[0]
        assert version == 1, f"Unsupported version: {version}"
        count = struct.unpack('B', f.read(1))[0]
        for _ in range(count):
            name_len = struct.unpack('B', f.read(1))[0]
            name = f.read(name_len).decode('ascii')
            data_len = struct.unpack('>H', f.read(2))[0]
            data = list(f.read(data_len))
            vectors[name] = data
    return vectors


def koopman_to_standard(koopman_hex_str):
    k = int(koopman_hex_str, 16)
    return (k << 1) | 1


def crc8(data_bytes, poly_std):
    gen = poly_std & 0xFF
    crc = 0
    for byte in data_bytes:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) & 0xFF) ^ gen
            else:
                crc = (crc << 1) & 0xFF
    return crc


def compute_period(poly_std):
    state = 1
    for k in range(1, 1024):
        state <<= 1
        if state & 0x100:
            state ^= poly_std
        state &= 0xFF
        if state == 1:
            return k
    return -1


def compute_remainders(poly_std, n):
    result = [1]
    state = 1
    for _ in range(1, n):
        state <<= 1
        if state & 0x100:
            state ^= poly_std
        state &= 0xFF
        result.append(state)
    return result


def max_dataword_hd3(poly_std):
    max_cw = 512
    r = compute_remainders(poly_std, max_cw)
    seen = {}
    for i in range(max_cw):
        if r[i] in seen:
            return i - 8
        seen[r[i]] = i
    return max_cw - 1 - 8


def max_dataword_hd4(poly_std):
    mcw3 = max_dataword_hd3(poly_std) + 8
    r = compute_remainders(poly_std, mcw3 + 1)
    seen = set()
    pairwise = set()
    for i in range(mcw3 + 1):
        if r[i] in seen:
            return max(0, i - 8)
        if r[i] in pairwise:
            return max(0, i - 8)
        for j in range(i):
            pairwise.add(r[i] ^ r[j])
        seen.add(r[i])
    return max(0, mcw3 - 8)


def int_to_gf2_poly(val):
    """Convert integer polynomial representation to sympy Poly over GF(2)."""
    terms = []
    i = 0
    v = val
    while v:
        if v & 1:
            terms.append(x ** i)
        v >>= 1
        i += 1
    return Poly(sum(terms), x, domain=GF(2))


def factor_info(poly_std):
    """Get GF(2) factorization info using sympy."""
    p = int_to_gf2_poly(poly_std)
    _, factors = p.factor_list()
    is_irred = len(factors) == 1 and factors[0][1] == 1
    degrees = sorted(
        [f.degree() for f, mult in factors for _ in range(mult)]
    )
    has_x_plus_1 = 1 in degrees
    return {
        'is_irreducible': is_irred,
        'factor_degrees': degrees,
        'has_x_plus_1_factor': has_x_plus_1,
    }


def run_c_engine(poly_std_hex, data_bytes):
    """Run compiled C engine to compute CRC-8."""
    tmp = f"/tmp/crc_input_{os.getpid()}.bin"
    with open(tmp, 'wb') as f:
        f.write(bytes(data_bytes))
    result = subprocess.run(
        ["/app/crc_engine", poly_std_hex, tmp],
        capture_output=True, text=True, check=True,
    )
    os.unlink(tmp)
    return int(result.stdout.strip())


def main():
    with open("/app/polynomials.json") as f:
        poly_data = json.load(f)

    vectors = parse_test_data("/app/test_data.bin")
    polys_koopman = poly_data["polynomials_koopman"]

    results = {"polynomials": {}}
    best_key = None
    best_val = -1

    for k_hex in polys_koopman:
        std = koopman_to_standard(k_hex)
        per = compute_period(std)
        hd3 = max_dataword_hd3(std)
        hd4 = max_dataword_hd4(std)

        crc_a = crc8(vectors["alpha"], std)
        crc_b = crc8(vectors["bravo"], std)
        crc_c = crc8(vectors["charlie"], std)

        # Cross-validate with compiled C engine
        c_a = run_c_engine(hex(std), vectors["alpha"])
        c_b = run_c_engine(hex(std), vectors["bravo"])
        c_c = run_c_engine(hex(std), vectors["charlie"])
        c_valid = (c_a == crc_a and c_b == crc_b and c_c == crc_c)

        finfo = factor_info(std)
        is_prim = finfo['is_irreducible'] and per == 255

        results["polynomials"][k_hex] = {
            "standard_hex": hex(std),
            "is_irreducible": finfo['is_irreducible'],
            "is_primitive": is_prim,
            "has_x_plus_1_factor": finfo['has_x_plus_1_factor'],
            "factor_degrees": finfo['factor_degrees'],
            "period": per,
            "max_dataword_hd3": hd3,
            "max_dataword_hd4": hd4,
            "crc_alpha": crc_a,
            "crc_bravo": crc_b,
            "crc_charlie": crc_c,
            "crc_c_validated": c_valid,
        }

        k_val = int(k_hex, 16)
        if hd4 > best_val or (hd4 == best_val and
                              (best_key is None or k_val < int(best_key, 16))):
            best_val = hd4
            best_key = k_hex

    results["best_hd4_polynomial"] = best_key

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
