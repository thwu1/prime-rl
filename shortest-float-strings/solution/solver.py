#!/usr/bin/env python3
"""Solve the IEEE 754 float serialization pipeline task.

Reads IEEE 754 doubles from /app/challenge.db, computes the shortest
round-trip-safe decimal strings, predecessor/successor floats, min_digits,
analyzes divergences with the buggy fast_convert, and writes /app/results.json.
"""

import struct
import math
import sqlite3
import json


def hex_to_double(h):
    """Convert a 16-char hex IEEE 754 bit-pattern string to a Python float."""
    return struct.unpack('>d', bytes.fromhex(h))[0]


def hex_to_bits(h):
    return int(h, 16)


def bits_to_hex(bits):
    return format(bits, '016X')


def shortest_repr(d):
    """Return (shortest_string, notation_type, min_digits) for the given double."""
    if math.isnan(d):
        return "NaN", "special", 0
    if math.isinf(d):
        return ("-Inf" if d < 0 else "Inf"), "special", 0
    if d == 0.0:
        return ("-0" if math.copysign(1.0, d) < 0 else "0"), "special", 0

    sign = "-" if d < 0 else ""
    ad = abs(d)
    target = struct.pack('>d', ad)

    # Find minimum significant digits for round-trip
    sci_str = None
    min_digits = 17
    for n in range(1, 18):
        s = f"{ad:.{n-1}e}"
        if struct.pack('>d', float(s)) == target:
            sci_str = s
            min_digits = n
            break

    if sci_str is None:
        sci_str = f"{ad:.16e}"

    # Parse Python's scientific notation
    parts = sci_str.split('e')
    mant = parts[0]
    exp = int(parts[1])

    if '.' in mant:
        ip, fp = mant.split('.')
        digits = ip + fp.rstrip('0')
    else:
        digits = mant

    # Build fixed notation
    dpos = exp + 1
    if dpos <= 0:
        fixed = "0." + "0" * (-dpos) + digits
    elif dpos >= len(digits):
        fixed = digits + "0" * (dpos - len(digits))
    else:
        fixed = digits[:dpos] + "." + digits[dpos:]

    # Build scientific notation
    if len(digits) == 1:
        sci = f"{digits}e{exp}"
    else:
        sci = f"{digits[0]}.{digits[1:]}e{exp}"

    # Pick shorter, ties go to fixed
    f_full = sign + fixed
    s_full = sign + sci

    if len(f_full) <= len(s_full):
        return f_full, "fixed", min_digits
    else:
        return s_full, "scientific", min_digits


def compute_pred_succ(hex_val):
    """Compute predecessor and successor hex values using IEEE 754 total order."""
    bits = hex_to_bits(hex_val)
    d = hex_to_double(hex_val)

    if math.isnan(d) or math.isinf(d):
        return None, None

    sign = bits >> 63

    # Predecessor (next smaller in total order)
    if sign == 0:  # positive or +0
        if bits == 0:  # +0 -> -0
            pred = 0x8000000000000000
        else:
            pred = bits - 1
    else:  # negative
        pred = bits + 1

    # Successor (next larger in total order)
    if sign == 0:  # positive or +0
        succ = bits + 1
    else:  # negative or -0
        mag = bits & 0x7FFFFFFFFFFFFFFF
        if mag == 0:  # -0 -> +0
            succ = 0x0000000000000000
        else:
            succ = bits - 1

    return bits_to_hex(pred), bits_to_hex(succ)


def simulate_fast_convert(hex_val):
    """Simulate the buggy fast_convert.c behavior."""
    d = hex_to_double(hex_val)

    if math.isnan(d):
        return "NaN"
    if math.isinf(d):
        return "-Inf" if d < 0 else "Inf"
    # Bug 1: no negative zero check
    if d == 0.0:
        return "0"

    ad = abs(d)
    target = struct.pack('>d', ad)
    sign = "-" if d < 0 else ""

    # Bug 2 & 3: uses %e format (padded exponents, always scientific)
    for p in range(0, 17):
        s = format(ad, f'.{p}e')
        if struct.pack('>d', float(s)) == target:
            return sign + s

    return sign + format(ad, '.16e')


def classify_divergence(fast_out, correct_out, hex_val):
    """Classify the bug type for a divergence."""
    if fast_out == "0" and correct_out == "-0":
        return "negative_zero"
    if 'e' not in correct_out:
        return "notation_selection"
    return "exponent_padding"


def main():
    conn = sqlite3.connect('/app/challenge.db')
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, hex_bits, category FROM ieee754_values ORDER BY id"
    )
    rows = cursor.fetchall()
    conn.close()

    results = []
    divergences = []
    summary = {}

    for row_id, hex_bits, category in rows:
        d = hex_to_double(hex_bits)
        shortest, notation, min_digits = shortest_repr(d)
        pred_hex, succ_hex = compute_pred_succ(hex_bits)

        results.append({
            "id": row_id,
            "hex_bits": hex_bits,
            "category": category,
            "shortest": shortest,
            "notation": notation,
            "min_digits": min_digits,
            "predecessor_hex": pred_hex,
            "successor_hex": succ_hex,
        })

        # Check for divergence with fast_convert
        fast_out = simulate_fast_convert(hex_bits)
        if fast_out != shortest:
            bug_class = classify_divergence(fast_out, shortest, hex_bits)
            divergences.append({
                "id": row_id,
                "fast_output": fast_out,
                "correct_output": shortest,
                "bug_class": bug_class,
            })

        # Accumulate summary statistics
        if category not in summary:
            summary[category] = {
                "count": 0,
                "scientific_count": 0,
                "fixed_count": 0,
                "special_count": 0,
            }
        summary[category]["count"] += 1
        summary[category][f"{notation}_count"] += 1

    output = {
        "results": results,
        "divergences": divergences,
        "summary": summary,
    }

    with open('/app/results.json', 'w') as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {len(results)} entries to /app/results.json")
    print(f"Found {len(divergences)} divergences with fast_convert")
    for cat, stats in sorted(summary.items()):
        print(f"  {cat}: {stats['count']} values "
              f"(fixed={stats['fixed_count']}, "
              f"sci={stats['scientific_count']}, "
              f"special={stats['special_count']})")


if __name__ == '__main__':
    main()
