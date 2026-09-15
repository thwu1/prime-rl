#!/usr/bin/env python3
"""Generate deterministic test data for cross-format float conformance audit.
Creates 5 data source files in heterogeneous formats under /app/data/.
"""
import struct
import math
import random
import json
import os

random.seed(0x1337CAFE)

def float_to_bits(d):
    return struct.unpack('<Q', struct.pack('<d', d))[0]

def bits_to_float(bits):
    return struct.unpack('<d', struct.pack('<Q', bits))[0]

# ============================================================
# Build pool of unique IEEE 754 doubles
# ============================================================
seen = set()
pool = []  # list of bit patterns (uint64)

def add(d):
    b = float_to_bits(d)
    if b not in seen:
        seen.add(b)
        pool.append(b)

# --- Special values ---
add(0.0)
add(bits_to_float(1 << 63))  # -0.0
add(float('inf'))
add(float('-inf'))
add(float('nan'))

# --- Subnormal values (exponent field = 0, mantissa != 0) ---
for i in [1, 2, 3, 5, 7, 15, 255, 1023, 65535,
          2**20, 2**30, 2**40, 2**50, 2**51, 2**52 - 1]:
    add(bits_to_float(i))
    add(bits_to_float(i | (1 << 63)))

# --- Powers of 2 across full exponent range ---
for e in range(-1074, 1024, 43):
    add(math.ldexp(1.0, e))
    add(-math.ldexp(1.0, e))

# --- Powers of 10 and IEEE 754 neighbors ---
for e in range(-22, 23):
    base = 10.0 ** e
    add(base)
    add(-base)
    bits = float_to_bits(base)
    if bits > 1:
        add(bits_to_float(bits + 1))
        add(bits_to_float(bits - 1))

# --- Notation-sensitive values (fixed vs scientific choice matters) ---
for v in [0.00011, 0.0001, 0.00099, 0.001, 0.0099, 0.01, 0.099, 0.1,
          0.99, 1.5, 9.9, 99.0, 100.0, 999.0, 1000.0,
          9999.0, 10000.0, 99999.0, 100000.0,
          1e6, 1e7, 1e8, 1e10, 1e15, 1e20,
          1e-5, 1e-10, 1e-15, 1e-20,
          3.5e4, 7.77e-3, 1.23e12, 4.56e-9]:
    add(v)
    add(-v)

# --- Mathematical constants and IEEE 754 boundary values ---
for v in [math.pi, math.e, math.sqrt(2), math.log(2), math.log(10),
          0.5, 0.25, 0.125, 0.0625, 0.03125,
          1.0/3.0, 1.0/7.0, 1.0/11.0, 1.0/13.0, 1.0/17.0,
          2.2250738585072014e-308, 5e-324,
          1.7976931348623157e+308, 1.7976931348623155e+308,
          0.1 + 0.2, 1.0 + 2**-52, 1.0 - 2**-53, 2.0 - 2**-52,
          float(1 << 53), float((1 << 53) - 1),
          9.999999999999998, 99.99999999999999,
          123456789.0, 123456789.123456789]:
    add(v)
    add(-v)

# --- Fill to 250 with random doubles ---
while len(pool) < 250:
    exp = random.randint(1, 2046)
    mantissa = random.randint(0, 2**52 - 1)
    sign = random.randint(0, 1)
    bits = (sign << 63) | (exp << 52) | mantissa
    add(bits_to_float(bits))

# ============================================================
# Assign values to 5 sources
# ============================================================
# Source 0: binary  (data/vectors/base_values.bin)
# Source 1: text    (data/samples/lab_readings.txt)
# Source 2: CSV     (data/imports/eu_sensor_data.csv) — European locale
# Source 3: hex     (data/reference/ieee754_hex.txt)
# Source 4: JSON    (data/archive/constants.json)

val_sources = {}  # bits -> set of source indices

for idx, bits in enumerate(pool):
    exp_field = (bits >> 52) & 0x7FF
    mant_field = bits & 0x000FFFFFFFFFFFFF
    srcs = set()

    if exp_field == 0x7FF or (exp_field == 0 and mant_field == 0):
        # Special values (inf, nan, zeros): binary + json
        srcs.update({0, 4})
    elif exp_field == 0 and mant_field != 0:
        # Subnormals: binary + hex
        srcs.update({0, 3})
    else:
        # Normal values: distribute with deterministic overlap
        primary = idx % 5
        srcs.add(primary)
        if idx % 4 == 0:
            secondary = (primary + 2) % 5
            srcs.add(secondary)

    val_sources[bits] = srcs

# Collect per-source lists and ensure minimums
src_values = {i: [] for i in range(5)}
for bits, srcs in val_sources.items():
    for s in srcs:
        src_values[s].append(bits)

# Rebalance: ensure each source has >= 25 values
for target in range(5):
    if len(src_values[target]) < 25:
        candidates = [b for b in pool if target not in val_sources[b]]
        random.shuffle(candidates)
        for b in candidates[:30 - len(src_values[target])]:
            val_sources[b].add(target)
            src_values[target].append(b)

# Sort for determinism
for s in src_values:
    src_values[s].sort()

# ============================================================
# Write source files
# ============================================================

# --- Source 0: Binary (4-byte LE count + N x 8-byte LE doubles) ---
os.makedirs('/app/data/vectors', exist_ok=True)
with open('/app/data/vectors/base_values.bin', 'wb') as f:
    vals = src_values[0]
    f.write(struct.pack('<I', len(vals)))
    for bits in vals:
        f.write(struct.pack('<Q', bits))

# --- Source 1: Text (one decimal per line, # comments, blank lines) ---
os.makedirs('/app/data/samples', exist_ok=True)
with open('/app/data/samples/lab_readings.txt', 'w') as f:
    f.write("# Laboratory measurement readings\n")
    f.write("# Format: one decimal float per line\n")
    f.write("# Lines starting with # are comments\n\n")
    for i, bits in enumerate(src_values[1]):
        d = bits_to_float(bits)
        if math.isnan(d):
            f.write("nan\n")
        elif math.isinf(d):
            f.write(f"{'-' if d < 0 else ''}inf\n")
        elif d == 0.0:
            f.write(f"{'-' if bits >> 63 else ''}0.0\n")
        else:
            f.write(f"{d!r}\n")
        if i % 11 == 7:
            f.write("\n")

# --- Source 2: CSV with European locale (semicolon delim, comma decimal) ---
os.makedirs('/app/data/imports', exist_ok=True)
with open('/app/data/imports/eu_sensor_data.csv', 'w') as f:
    f.write("sensor_id;timestamp;value;unit\n")
    for idx, bits in enumerate(src_values[2]):
        d = bits_to_float(bits)
        sensor = f"SEN-{idx+1:04d}"
        ts = f"2024-{(idx%12)+1:02d}-{(idx%28)+1:02d}"
        if math.isnan(d):
            val_str = "NaN"
        elif math.isinf(d):
            val_str = "-Inf" if d < 0 else "Inf"
        elif d == 0.0:
            val_str = "-0,0" if bits >> 63 else "0,0"
        else:
            val_str = f"{d!r}".replace('.', ',')
        f.write(f"{sensor};{ts};{val_str};mV\n")

# --- Source 3: Hex IEEE 754 bit patterns ---
os.makedirs('/app/data/reference', exist_ok=True)
with open('/app/data/reference/ieee754_hex.txt', 'w') as f:
    f.write("# IEEE 754 double-precision hex bit patterns\n")
    f.write("# Format: 0x followed by 16 uppercase hex digits\n\n")
    for bits in src_values[3]:
        f.write(f"0x{bits:016X}\n")

# --- Source 4: JSON with string values ---
os.makedirs('/app/data/archive', exist_ok=True)
json_values = []
for bits in src_values[4]:
    d = bits_to_float(bits)
    if math.isnan(d):
        json_values.append("NaN")
    elif math.isinf(d):
        json_values.append("-Infinity" if d < 0 else "Infinity")
    elif d == 0.0:
        json_values.append("-0" if bits >> 63 else "0")
    else:
        json_values.append(f"{d!r}")
with open('/app/data/archive/constants.json', 'w') as f:
    json.dump({
        "metadata": {"format": "numeric_strings", "version": 2},
        "values": json_values
    }, f, indent=2)

# ============================================================
# Summary
# ============================================================
total_unique = len(pool)
print(f"Generated {total_unique} unique IEEE 754 doubles across 5 sources:")
source_names = ['binary', 'text', 'csv_european', 'hex', 'json']
for i, name in enumerate(source_names):
    print(f"  {name}: {len(src_values[i])} values")
overlap = sum(1 for s in val_sources.values() if len(s) > 1)
print(f"  Values in multiple sources: {overlap}")
