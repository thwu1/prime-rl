#!/usr/bin/env python3

"""Cross-format float conformance audit solver.

Discovers all data sources under /app/data/, parses each according to its
format, computes shortest round-trip-safe decimal strings, and writes
/app/output/audit.csv.
"""

import struct
import math
import os
import json


# ========================
# IEEE 754 helpers
# ========================

def float_to_bits(d):
    return struct.unpack('<Q', struct.pack('<d', d))[0]


def bits_to_float(bits):
    return struct.unpack('<d', struct.pack('<Q', bits))[0]


def classify(bits):
    exp = (bits >> 52) & 0x7FF
    mant = bits & 0x000FFFFFFFFFFFFF
    if exp == 0x7FF:
        return "nan" if mant else "infinity"
    if exp == 0 and mant == 0:
        return "zero"
    if exp == 0:
        return "subnormal"
    return "normal"


# ========================
# Shortest string algorithm
# ========================

def find_min_sig(d_abs, abs_bits):
    """Minimum significant digits for exact round-trip."""
    for n in range(1, 18):
        s = f"{d_abs:.{n-1}e}"
        if float_to_bits(float(s)) == abs_bits:
            return n
    return 17


def gen_fixed(d_abs, sig):
    s = f"{d_abs:.{sig-1}e}"
    parts = s.split('e')
    digits = parts[0].replace('.', '').replace('-', '')
    exp = int(parts[1])
    if exp >= sig - 1:
        result = digits + '0' * (exp - sig + 1)
    elif exp >= 0:
        result = digits[:exp+1] + '.' + digits[exp+1:]
    else:
        result = '0.' + '0' * (-exp-1) + digits
    if '.' in result:
        result = result.rstrip('0').rstrip('.')
    return result


def gen_sci(d_abs, sig):
    s = f"{d_abs:.{sig-1}e}"
    parts = s.split('e')
    mantissa = parts[0]
    exp = int(parts[1])
    if '.' in mantissa:
        mantissa = mantissa.rstrip('0').rstrip('.')
    return f"{mantissa}e{exp}"


def shortest_string(bits):
    exp_field = (bits >> 52) & 0x7FF
    mant_field = bits & 0x000FFFFFFFFFFFFF
    sign = bits >> 63
    if exp_field == 0x7FF:
        return "nan" if mant_field else ("-inf" if sign else "inf")
    d = bits_to_float(bits)
    if d == 0.0:
        return "-0" if sign else "0"
    prefix = "-" if sign else ""
    d_abs = abs(d)
    abs_bits = bits & 0x7FFFFFFFFFFFFFFF
    n = find_min_sig(d_abs, abs_bits)
    fixed = prefix + gen_fixed(d_abs, n)
    sci = prefix + gen_sci(d_abs, n)
    return fixed if len(fixed) <= len(sci) else sci


# ========================
# Data source parsers
# ========================

def parse_binary(path):
    result = []
    with open(path, 'rb') as f:
        count = struct.unpack('<I', f.read(4))[0]
        for _ in range(count):
            bits = struct.unpack('<Q', f.read(8))[0]
            result.append(bits)
    return result


def parse_text(path):
    result = []
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            try:
                result.append(float_to_bits(float(line)))
            except ValueError:
                pass
    return result


def parse_hex_patterns(path):
    result = []
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            try:
                bits = int(line, 16)
                result.append(bits)
            except ValueError:
                pass
    return result


def parse_csv_european(path):
    result = []
    with open(path, 'r') as f:
        header = f.readline()
        # Determine delimiter
        delim = ';' if ';' in header else ','
        # Find value column
        cols = [c.strip().lower() for c in header.split(delim)]
        val_idx = next((i for i, c in enumerate(cols) if 'value' in c), 2)

        for line in f:
            line = line.strip()
            if not line:
                continue
            fields = line.split(delim)
            if len(fields) <= val_idx:
                continue
            val_str = fields[val_idx].strip()
            low = val_str.lower()
            if low == 'nan':
                result.append(float_to_bits(float('nan')))
            elif low in ('inf', 'infinity'):
                result.append(float_to_bits(float('inf')))
            elif low in ('-inf', '-infinity'):
                result.append(float_to_bits(float('-inf')))
            else:
                val_str = val_str.replace(',', '.')
                try:
                    result.append(float_to_bits(float(val_str)))
                except ValueError:
                    pass
    return result


def parse_json_file(path):
    with open(path, 'r') as f:
        data = json.load(f)
    values_list = None
    if isinstance(data, dict) and 'values' in data:
        values_list = data['values']
    elif isinstance(data, list):
        values_list = data
    if not values_list:
        return []
    result = []
    for s in values_list:
        if not isinstance(s, str):
            continue
        s = s.strip()
        low = s.lower()
        if low == 'nan':
            result.append(float_to_bits(float('nan')))
        elif low in ('infinity', 'inf'):
            result.append(float_to_bits(float('inf')))
        elif low in ('-infinity', '-inf'):
            result.append(float_to_bits(float('-inf')))
        else:
            try:
                result.append(float_to_bits(float(s)))
            except ValueError:
                pass
    return result


def detect_and_parse(filepath):
    """Auto-detect format and parse a data file."""
    ext = os.path.splitext(filepath)[1].lower()

    if ext == '.bin':
        return parse_binary(filepath)
    elif ext == '.json':
        return parse_json_file(filepath)
    elif ext == '.csv':
        return parse_csv_european(filepath)
    elif ext == '.txt':
        # Distinguish hex pattern files from decimal text files
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if line.startswith('0x') or line.startswith('0X'):
                    return parse_hex_patterns(filepath)
                else:
                    return parse_text(filepath)
        return []
    return []


# ========================
# Main
# ========================

def main():
    data_dir = '/app/data'
    all_values = {}  # bits -> set of source file paths

    # Discover and parse all data sources
    for root, dirs, files in os.walk(data_dir):
        for filename in files:
            filepath = os.path.join(root, filename)
            try:
                bits_list = detect_and_parse(filepath)
                for bits in bits_list:
                    if bits not in all_values:
                        all_values[bits] = set()
                    all_values[bits].add(filepath)
                print(f"Parsed {filepath}: {len(bits_list)} values")
            except Exception as e:
                print(f"Error parsing {filepath}: {e}")

    print(f"\nTotal unique bit patterns: {len(all_values)}")

    # Generate output
    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/audit.csv', 'w') as f:
        for bits in sorted(all_values.keys()):
            hex_str = f"{bits:016x}"
            short = shortest_string(bits)
            src_count = len(all_values[bits])
            cat = classify(bits)
            f.write(f"{hex_str},{short},{src_count},{cat}\n")

    print(f"Wrote {len(all_values)} rows to /app/output/audit.csv")


if __name__ == '__main__':
    main()
