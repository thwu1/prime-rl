#!/usr/bin/env python3
"""Generate data files for the division lookup table reverse-engineering task.

This script runs during Docker build (builder stage) and is NOT included
in the final image, so the agent cannot inspect it.
"""
import struct
import csv
import math
from fractions import Fraction
from collections import defaultdict


def generate_table(buggy=False):
    """Generate the radix-4 SRT quotient selection lookup table."""
    table = {}
    adj = Fraction(1, 8)
    for d_idx in range(16):
        d = Fraction(1) + Fraction(d_idx, 16)
        for p_idx in range(-64, 64):
            p = Fraction(p_idx, 8)
            outer = Fraction(8, 3) * d - (adj if buggy else Fraction(0))
            if p > outer or p < -outer:
                table[(d_idx, p_idx)] = 0
                continue
            t2 = Fraction(4, 3) * d
            t1 = Fraction(1, 3) * d
            if p >= 0:
                if p >= t2:
                    table[(d_idx, p_idx)] = 2
                elif p >= t1:
                    table[(d_idx, p_idx)] = 1
                else:
                    table[(d_idx, p_idx)] = 0
            else:
                if p <= -t2 - adj:
                    table[(d_idx, p_idx)] = -2
                elif p <= -t1 - adj:
                    table[(d_idx, p_idx)] = -1
                else:
                    table[(d_idx, p_idx)] = 0
    return table


def save_binary_table(table, filename):
    """Save table as raw binary in hardware address order.

    Format: 2048 signed bytes.
    byte_offset = d_idx * 128 + (p_idx & 0x7F)
    where p_idx & 0x7F maps: 0..63 -> 0..63, -64..-1 -> 64..127
    """
    data = bytearray(2048)
    for d_idx in range(16):
        for p_idx in range(-64, 64):
            hw = p_idx & 0x7F
            offset = d_idx * 128 + hw
            q = table[(d_idx, p_idx)]
            data[offset] = struct.pack('b', q)[0]
    with open(filename, 'wb') as f:
        f.write(bytes(data))


def decompose_range(start, end):
    """Decompose integer range [start, end] into aligned power-of-2 blocks.
    Returns list of (value, size) tuples."""
    blocks = []
    p = start
    while p <= end:
        size = 1
        while size * 2 <= end - p + 1 and (p % (size * 2)) == 0:
            size *= 2
        blocks.append((p, size))
        p += size
    return blocks


def generate_pla(table, filename):
    """Generate Espresso-format PLA for the lookup table.

    The PLA has 11 inputs (d3 d2 d1 d0 p6 p5 p4 p3 p2 p1 p0) and 2 outputs
    (mag1: |q|>=1, mag2: |q|=2). The sign of q is NOT encoded in the PLA;
    it is derived from the sign of the partial remainder (p6 bit).

    Outputs are mutually exclusive: mag1=1 means |q|=1, mag2=1 means |q|=2.
    """
    mag1_entries = []
    mag2_entries = []

    for d_idx in range(16):
        for p_idx in range(-64, 64):
            q = table[(d_idx, p_idx)]
            hw = p_idx & 0x7F
            if abs(q) == 1:
                mag1_entries.append((d_idx, hw))
            elif abs(q) == 2:
                mag2_entries.append((d_idx, hw))

    def entries_to_terms(entries, output_str):
        terms = []
        by_d = defaultdict(list)
        for d_idx, hw in entries:
            by_d[d_idx].append(hw)

        for d_idx in sorted(by_d.keys()):
            d_bits = format(d_idx, '04b')
            hw_list = sorted(by_d[d_idx])

            # Find contiguous ranges of hw addresses
            ranges = []
            rstart = hw_list[0]
            rend = hw_list[0]
            for hw in hw_list[1:]:
                if hw == rend + 1:
                    rend = hw
                else:
                    ranges.append((rstart, rend))
                    rstart = hw
                    rend = hw
            ranges.append((rstart, rend))

            for rs, re in ranges:
                for val, size in decompose_range(rs, re):
                    dc = 0
                    s = size
                    while s > 1:
                        dc += 1
                        s >>= 1
                    p_bits = list(format(val, '07b'))
                    for i in range(dc):
                        p_bits[6 - i] = '-'
                    terms.append(d_bits + ''.join(p_bits) + ' ' + output_str)
        return terms

    terms = entries_to_terms(mag1_entries, '10')
    terms.extend(entries_to_terms(mag2_entries, '01'))

    with open(filename, 'w') as f:
        f.write('# Division quotient-selection PLA\n')
        f.write('# Corrected revision — extracted from fixed processor die\n')
        f.write('#\n')
        f.write('# Inputs:  d3 d2 d1 d0  (4-bit truncated divisor index)\n')
        f.write('#          p6 p5 p4 p3 p2 p1 p0  (7-bit partial remainder index, 2s complement)\n')
        f.write('# Outputs: mag1 mag2  (quotient digit magnitude flags)\n')
        f.write('#          mag1=1,mag2=0 => |q|=1;  mag1=0,mag2=1 => |q|=2\n')
        f.write('#          Both 0 => q=0. Sign of q = sign of partial remainder.\n')
        f.write('#\n')
        f.write('.i 11\n')
        f.write('.o 2\n')
        f.write('.ilb d3 d2 d1 d0 p6 p5 p4 p3 p2 p1 p0\n')
        f.write('.ob mag1 mag2\n')
        f.write(f'.p {len(terms)}\n')
        for t in terms:
            f.write(t + '\n')
        f.write('.e\n')


def srt_divide(a, d, table, num_steps=34):
    """Perform SRT division using the given lookup table."""
    w = a
    d_idx = int((d - 1.0) * 16)
    d_idx = max(0, min(15, d_idx))
    quotient = 0.0
    scale = 1.0
    for _ in range(num_steps):
        p_idx = int(math.floor(w * 8))
        p_idx = max(-64, min(63, p_idx))
        q = table.get((d_idx, p_idx), 0)
        quotient += q * scale
        scale /= 4.0
        w = 4.0 * (w - q * d)
    return quotient


def generate_test_vectors(correct_table, filename):
    """Generate known-correct division test cases for simulator validation."""
    cases = [
        (1.5, 1.25),
        (1.0, 1.0),
        (1.8, 1.2),
        (1.5, 1.0),
        (1.75, 1.5),
        (1.999, 1.001),
        (1.1, 1.9),
        (1.333, 1.777),
        (1.0625, 1.9375),
        (1.5, 1.5),
        (1.95, 1.05),
        (1.125, 1.875),
    ]
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['dividend_sig', 'divisor_sig', 'expected_quotient'])
        for a, d in cases:
            q = a / d  # mathematically correct result
            writer.writerow([f'{a:.15f}', f'{d:.15f}', f'{q:.15f}'])


if __name__ == '__main__':
    correct = generate_table(buggy=False)
    buggy = generate_table(buggy=True)

    save_binary_table(buggy, '/data/buggy_rom.bin')
    generate_pla(correct, '/data/fixed_rom.pla')
    generate_test_vectors(correct, '/data/test_vectors.csv')

    diffs = sum(1 for k in correct if correct[k] != buggy[k])
    print(f"Generated data files. Table differences: {diffs}")
