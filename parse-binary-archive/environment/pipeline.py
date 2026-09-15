#!/usr/bin/env python3
"""Data processing pipeline: parse numbers and compute aggregate statistics."""
import ctypes
import struct
import json
import sys
import os
import argparse


def load_library(path):
    """Load a fast number parsing shared library."""
    if not os.path.exists(path):
        print(f"ERROR: {path} not found.", file=sys.stderr)
        sys.exit(1)
    lib = ctypes.CDLL(path)
    lib.fast_parse_double.argtypes = [
        ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_double)
    ]
    lib.fast_parse_double.restype = ctypes.c_int
    return lib


def bits_of(d):
    """Return the uint64 bit pattern of an IEEE 754 binary64 value."""
    return struct.unpack('<Q', struct.pack('<d', d))[0]


def main():
    parser = argparse.ArgumentParser(
        description='Parse numbers via a C library and compute aggregate stats.')
    parser.add_argument('--lib', required=True, help='Path to parser .so library')
    parser.add_argument('--output', default='/app/results.json', help='Output path')
    args = parser.parse_args()

    lib = load_library(args.lib)

    with open('/app/data/input.txt') as f:
        lines = [line.strip() for line in f if line.strip()]

    values = []
    errors = 0
    for i, line in enumerate(lines):
        result = ctypes.c_double()
        encoded = line.encode('ascii')
        rc = lib.fast_parse_double(encoded, len(encoded), ctypes.byref(result))
        if rc != 0:
            print(f"Parse error on line {i+1}: {line!r}", file=sys.stderr)
            errors += 1
            continue
        values.append(result.value)

    if errors:
        print(f"WARNING: {errors} parse error(s)", file=sys.stderr)

    xor_acc = 0
    neg_zero_count = 0
    subnormal_count = 0

    for v in values:
        bits = bits_of(v)
        xor_acc ^= bits
        if bits == 0x8000000000000000:
            neg_zero_count += 1
        exp_field = (bits >> 52) & 0x7FF
        sig_field = bits & ((1 << 52) - 1)
        if exp_field == 0 and sig_field != 0:
            subnormal_count += 1

    # Kahan-compensated sum
    s = c = 0.0
    for v in values:
        y = v - c
        t = s + y
        c = (t - s) - y
        s = t

    output = {
        "total_count": len(values),
        "xor_hash": f"{xor_acc:016x}",
        "kahan_sum_hex": f"{bits_of(s):016x}",
        "negative_zero_count": neg_zero_count,
        "subnormal_count": subnormal_count,
    }

    with open(args.output, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"Processed {len(values)} numbers -> {args.output}")


if __name__ == '__main__':
    main()
