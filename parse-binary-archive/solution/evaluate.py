#!/usr/bin/env python3
"""Evaluate three parser libraries for IEEE 754 conformance and produce reports.

Loads each parser, runs conformance tests and the full dataset, classifies
failures by IEEE 754 edge-case category, and produces:
  - /app/conformance_tests.csv  (test corpus)
  - /app/evaluation.json        (ranking and per-parser analysis)
"""

import ctypes
import struct
import json
import csv
import os


def bits_of(d):
    return struct.unpack('<Q', struct.pack('<d', d))[0]


def load_parser(path):
    lib = ctypes.CDLL(path)
    lib.fast_parse_double.argtypes = [
        ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_double)
    ]
    lib.fast_parse_double.restype = ctypes.c_int
    return lib


def c_parse(lib, s):
    result = ctypes.c_double()
    encoded = s.encode('ascii') if isinstance(s, str) else s
    rc = lib.fast_parse_double(encoded, len(encoded), ctypes.byref(result))
    if rc != 0:
        return None
    return result.value


def classify_input(s):
    """Classify a float string by IEEE 754 edge-case category."""
    v = float(s)
    b = bits_of(v)
    exp_field = (b >> 52) & 0x7FF
    sig_field = b & ((1 << 52) - 1)

    if b == 0x8000000000000000:
        return "negative_zero"
    if b == 0x0000000000000000 and s.strip().startswith('-'):
        return "negative_zero"
    if exp_field == 0x7FF:
        return "overflow"
    if exp_field == 0 and sig_field != 0:
        return "subnormal"
    if v != 0.0 and abs(v) <= 5e-308:
        return "boundary"

    # Check if the input exercises extended fast-path exponents
    # by looking for explicit exponent in [23, 37] range
    s_stripped = s.strip().lstrip('+-')
    if 'e' in s_stripped or 'E' in s_stripped:
        parts = s_stripped.replace('E', 'e').split('e')
        if len(parts) == 2:
            try:
                explicit_exp = int(parts[1])
                if 23 <= abs(explicit_exp) <= 200:
                    return "precision"
            except ValueError:
                pass

    return "normal"


# Conformance test corpus design
CORPUS = [
    # negative_zero: strings that must parse to -0.0
    ("-0.0", "negative_zero"),
    ("-0e0", "negative_zero"),
    ("-0.0e10", "negative_zero"),
    ("-0.00", "negative_zero"),
    ("-0e-5", "negative_zero"),
    ("-0.0e-100", "negative_zero"),

    # subnormal: values in (0, DBL_MIN)
    ("5e-324", "subnormal"),
    ("4.9406564584124654e-324", "subnormal"),
    ("1e-310", "subnormal"),
    ("1e-315", "subnormal"),
    ("1e-320", "subnormal"),
    ("1e-309", "subnormal"),
    ("1e-323", "subnormal"),
    ("2.2250738585072013e-308", "subnormal"),
    ("1.5e-310", "subnormal"),
    ("9.9e-321", "subnormal"),

    # boundary: values at or very near DBL_MIN
    ("2.2250738585072014e-308", "boundary"),
    ("2.2250738585072019e-308", "boundary"),
    ("3e-308", "boundary"),
    ("1e-308", "boundary"),
    ("2e-308", "boundary"),

    # precision: values requiring extended fast-path or careful rounding
    ("1e23", "precision"),
    ("1e30", "precision"),
    ("1e35", "precision"),
    ("5e25", "precision"),
    ("1e24", "precision"),
    ("1e28", "precision"),
    # 19-digit mantissa with large exponent (tests slow-path buffer limits)
    ("1234567890123456789e-320", "precision"),
    ("9999999999999999999e-340", "precision"),
    ("1234567890123456789e-200", "precision"),
    ("1000000000000000000e-330", "precision"),

    # overflow: values at or beyond DBL_MAX
    ("1e309", "overflow"),
    ("-1e309", "overflow"),
    ("1e310", "overflow"),
    ("1e400", "overflow"),
    ("-1e400", "overflow"),
]


def main():
    # Write conformance test corpus
    with open('/app/conformance_tests.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['input_string', 'category'])
        writer.writeheader()
        for s, cat in CORPUS:
            writer.writerow({'input_string': s, 'category': cat})
    print(f"Wrote {len(CORPUS)} entries to /app/conformance_tests.csv")

    # Load all three parsers
    parsers = {
        "alpha": load_parser('/app/parsers/libparser_alpha.so'),
        "beta": load_parser('/app/parsers/libparser_beta.so'),
        "gamma": load_parser('/app/parsers/libparser_gamma.so'),
    }

    # Load full dataset
    with open('/app/data/input.txt') as f:
        dataset_inputs = [line.strip() for line in f if line.strip()]

    # Combine corpus inputs with dataset (deduplicated)
    all_inputs = [s for s, _ in CORPUS] + dataset_inputs
    seen = set()
    unique_inputs = []
    for s in all_inputs:
        if s not in seen:
            seen.add(s)
            unique_inputs.append(s)

    # Evaluate each parser
    evaluation = {}
    failure_counts = {}

    for name, lib in parsers.items():
        failures = []
        categories = {}

        for s in unique_inputs:
            try:
                expected = float(s)
                actual = c_parse(lib, s)
                if actual is None or bits_of(actual) != bits_of(expected):
                    cat = classify_input(s)
                    failures.append({"input": s, "category": cat,
                                     "expected_hex": f"0x{bits_of(expected):016x}",
                                     "actual_hex": f"0x{bits_of(actual):016x}" if actual is not None else "parse_error"})
                    categories[cat] = categories.get(cat, 0) + 1
            except Exception:
                pass

        evaluation[name] = {
            "failure_count": len(failures),
            "categories": categories,
            "sample_failures": failures[:25],
        }
        failure_counts[name] = len(failures)

    # Rank by failure count ascending (best first)
    ranking = sorted(failure_counts, key=lambda x: failure_counts[x])
    evaluation["ranking"] = ranking

    with open('/app/evaluation.json', 'w') as f:
        json.dump(evaluation, f, indent=2)

    print(f"Evaluation complete.")
    print(f"  Ranking (best to worst): {ranking}")
    for name in ranking:
        print(f"  {name}: {failure_counts[name]} failures — {evaluation[name]['categories']}")


if __name__ == '__main__':
    main()
