#!/usr/bin/env python3
"""Fix all 6 bugs in the fpdetect numerical anomaly detection framework.

Bug 1 (ieee754.py): float32_to_bits uses mismatched endianness — packs float
       as big-endian but unpacks uint32 as little-endian, producing byte-swapped
       bit patterns that corrupt all IEEE 754 field extraction and mutation.

Bug 2 (ieee754.py): to_float32 uses round(value, 7) which rounds to 7 decimal
       places. This is NOT equivalent to IEEE 754 float32 truncation — float32
       has ~7 significant DIGITS but round(x, 7) operates on DECIMAL PLACES.
       Large values keep too much precision; small values round to zero.

Bug 3 (ieee754.py): relative_error divides by abs(reference) without checking
       for zero, causing ZeroDivisionError on inputs where the reference is 0.

Bug 4 (detection.py): detect_precision_loss compares the absolute difference
       against the threshold. For large values (e.g. exp(20) ≈ 4.85e8), the
       absolute diff is large even when relative error is negligible, causing
       false positives. Must use relative error.

Bug 5 (detection.py): detect_special_value only checks positive infinity
       (math.isinf(value) and value > 0), missing negative infinity entirely.

Bug 6 (fuzzer.py): is_within_range uses `not (value < ... or value > ...)`.
       NaN comparisons always return False, so NaN passes through as "in range",
       contaminating the fuzzer's internal state.
"""

import os


def fix_file(filepath, replacements):
    """Apply a list of (old, new) string replacements to a file."""
    with open(filepath, 'r') as f:
        content = f.read()
    for old, new in replacements:
        if old not in content:
            print(f"WARNING: pattern not found in {filepath}:")
            print(f"  {old[:80]}...")
            continue
        content = content.replace(old, new, 1)
    with open(filepath, 'w') as f:
        f.write(content)
    print(f"Fixed: {filepath}")


def main():
    # Bug 1: Fix endianness mismatch in float32_to_bits
    # Bug 2: Fix to_float32 to use struct round-trip instead of decimal rounding
    # Bug 3: Fix relative_error to handle zero reference
    fix_file('/app/fpdetect/ieee754.py', [
        (
            "return struct.unpack('<I', packed)[0]",
            "return struct.unpack('>I', packed)[0]",
        ),
        (
            "return round(value, 7)",
            "try:\n"
            "        return struct.unpack('>f', struct.pack('>f', value))[0]\n"
            "    except (OverflowError, struct.error):\n"
            "        return math.copysign(float('inf'), value)",
        ),
        (
            "    return abs(measured - reference) / abs(reference)",
            "    if reference == 0.0:\n"
            "        return 0.0 if measured == 0.0 else float('inf')\n"
            "    return abs(measured - reference) / abs(reference)",
        ),
    ])

    # Bug 4: Fix precision loss detection to use relative error
    # Bug 5: Fix special value detection to include negative infinity
    fix_file('/app/fpdetect/detection.py', [
        (
            "    diff = abs(f32_result - f64_result)\n"
            "    if diff > threshold:\n"
            "        return True, diff\n"
            "    return False, diff",

            "    if f64_result == 0.0:\n"
            "        diff = abs(f32_result)\n"
            "    else:\n"
            "        diff = abs(f32_result - f64_result) / abs(f64_result)\n"
            "    if diff > threshold:\n"
            "        return True, diff\n"
            "    return False, diff",
        ),
        (
            "if math.isinf(value) and value > 0:",
            "if math.isinf(value):",
        ),
    ])

    # Bug 6: Fix is_within_range to reject NaN and Inf
    fix_file('/app/fpdetect/fuzzer.py', [
        (
            "        return not (value < -3.40E38 or value > 3.40E38)",
            "        if math.isnan(value) or math.isinf(value):\n"
            "            return False\n"
            "        return -3.40E38 <= value <= 3.40E38",
        ),
    ])

    print("All 6 bugs fixed successfully.")


if __name__ == '__main__':
    main()
