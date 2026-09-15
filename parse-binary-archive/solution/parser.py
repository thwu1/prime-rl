#!/usr/bin/env python3
"""Reference solution: parse NUMDATA1 archive and compute aggregates."""

import struct
import base64
import json


def bits_of(d):
    """IEEE 754 binary64 -> uint64 bit pattern."""
    return struct.unpack('<Q', struct.pack('<d', d))[0]


def parse_archive(filepath):
    """Read NUMDATA1 and return list of (double_value, type_tag) tuples."""
    with open(filepath, 'rb') as fh:
        data = fh.read()

    assert data[:8] == b"NUMDATA1", "Invalid magic header"
    record_count = struct.unpack_from('<I', data, 8)[0]

    offset = 12
    results = []

    for _ in range(record_count):
        tag = data[offset]
        offset += 1

        if tag == 1:
            # Raw IEEE 754 binary64, little-endian
            value = struct.unpack_from('<d', data, offset)[0]
            offset += 8

        elif tag == 2:
            # Decimal ASCII string
            str_len = struct.unpack_from('<H', data, offset)[0]
            offset += 2
            text = data[offset:offset + str_len].decode('ascii')
            offset += str_len
            value = float(text)

        elif tag == 3:
            # Base64-encoded binary64
            b64_len = struct.unpack_from('<H', data, offset)[0]
            offset += 2
            b64_text = data[offset:offset + b64_len]
            offset += b64_len
            raw_bytes = base64.b64decode(b64_text)
            value = struct.unpack('<d', raw_bytes)[0]

        elif tag == 4:
            # Hex float string
            str_len = struct.unpack_from('<H', data, offset)[0]
            offset += 2
            text = data[offset:offset + str_len].decode('ascii')
            offset += str_len
            value = float.fromhex(text)

        elif tag == 5:
            # Scaled integer: big-endian int64 mantissa + uint8 scale
            mantissa = struct.unpack_from('>q', data, offset)[0]
            offset += 8
            scale = data[offset]
            offset += 1
            value = mantissa * (10.0 ** (-scale))

        else:
            raise ValueError(f"Unknown type tag: 0x{tag:02x} at offset {offset - 1}")

        results.append((value, tag))

    return results


def main():
    entries = parse_archive('/app/data.bin')
    values = [v for v, _ in entries]
    tags = [t for _, t in entries]

    # --- XOR hash ---
    xor_acc = 0
    for v in values:
        xor_acc ^= bits_of(v)

    # --- Kahan-compensated sum ---
    kahan_s = 0.0
    kahan_c = 0.0
    for v in values:
        y = v - kahan_c
        t = kahan_s + y
        kahan_c = (t - kahan_s) - y
        kahan_s = t

    # --- Type counts ---
    type_counts = {}
    for t in [1, 2, 3, 4, 5]:
        type_counts[str(t)] = sum(1 for tag in tags if tag == t)

    # --- Negative zero count ---
    neg_zero_count = sum(1 for v in values if bits_of(v) == 0x8000000000000000)

    # --- Subnormal count ---
    subnormal_count = 0
    for v in values:
        b = bits_of(v)
        exponent = (b >> 52) & 0x7FF
        significand = b & ((1 << 52) - 1)
        if exponent == 0 and significand != 0:
            subnormal_count += 1

    # --- Write results.json ---
    output = {
        "total_count": len(values),
        "type_counts": type_counts,
        "xor_hash": f"{xor_acc:016x}",
        "kahan_sum_hex": f"{bits_of(kahan_s):016x}",
        "negative_zero_count": neg_zero_count,
        "subnormal_count": subnormal_count,
    }
    with open('/app/results.json', 'w') as fh:
        json.dump(output, fh, indent=2)

    # --- Write values.bin ---
    with open('/app/values.bin', 'wb') as fh:
        for v in values:
            fh.write(struct.pack('<d', v))


if __name__ == '__main__':
    main()
