#!/usr/bin/env python3
"""
Conformance audit of three CBOR deterministic encoders against
RFC 8949 Section 4.2.1 Core Deterministic Encoding Requirements.

Produces /app/conformance_report.json.
"""


import subprocess
import json
import sys


def run(path, hex_in):
    """Run an encoder on a single hex-encoded CBOR item."""
    r = subprocess.run(
        ["python3", path],
        input=hex_in + "\n",
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        print(f"  WARN: {path} failed on {hex_in}: {r.stderr}", file=sys.stderr)
        return None
    return r.stdout.strip()


ENCODERS = {
    "alpha": "/app/encoders/alpha.py",
    "beta": "/app/encoders/beta.py",
    "gamma": "/app/encoders/gamma.py",
}


def check_preferred_int_args(path):
    """Test that integer arguments use shortest encoding form."""
    # uint 255 must stay in u8 form (18ff), not widen to u16 (1900ff)
    if run(path, "18ff") != "18ff":
        return "fail"
    # uint 255 encoded as u16 must normalize down to u8
    if run(path, "1900ff") != "18ff":
        return "fail"
    # uint 0 in u8 form must collapse to inline
    if run(path, "1800") != "00":
        return "fail"
    # uint 23 in u8 must collapse to inline
    if run(path, "1817") != "17":
        return "fail"
    # negative -1 in s8 must collapse to inline
    if run(path, "3800") != "20":
        return "fail"
    # negative -256 in s16 must collapse to s8
    if run(path, "3900ff") != "38ff":
        return "fail"
    return "pass"


def check_preferred_float_nan(path):
    """Test that all NaN values are canonicalized to f16 quiet NaN."""
    # f64 NaN -> f97e00
    if run(path, "fb7ff8000000000000") != "f97e00":
        return "fail"
    # f32 NaN -> f97e00
    if run(path, "fa7fc00000") != "f97e00":
        return "fail"
    # f16 canonical NaN must pass through
    if run(path, "f97e00") != "f97e00":
        return "fail"
    return "pass"


def check_preferred_float_neg_zero(path):
    """Test that negative zero sign bit is preserved."""
    # f32 -0.0 -> f98000
    if run(path, "fa80000000") != "f98000":
        return "fail"
    # f64 -0.0 -> f98000
    if run(path, "fb8000000000000000") != "f98000":
        return "fail"
    # f16 -0.0 must pass through
    if run(path, "f98000") != "f98000":
        return "fail"
    return "pass"


def check_preferred_float_shortest(path):
    """Test that floats use shortest IEEE 754 precision."""
    # f64 1.0 -> f16
    if run(path, "fb3ff0000000000000") != "f93c00":
        return "fail"
    # f32 1.0 -> f16
    if run(path, "fa3f800000") != "f93c00":
        return "fail"
    # f64 100000.0 -> f32 (too large for f16)
    if run(path, "fb40f86a0000000000") != "fa47c35000":
        return "fail"
    # f32 100000.0 must stay f32
    if run(path, "fa47c35000") != "fa47c35000":
        return "fail"
    # f64 1.1 must stay f64 (not exact in lower precisions)
    if run(path, "fb3ff199999999999a") != "fb3ff199999999999a":
        return "fail"
    return "pass"


def check_no_indefinite_length(path):
    """Test that indefinite-length items are converted to definite."""
    # indefinite array [1,2,3] -> definite
    if run(path, "9f010203ff") != "83010203":
        return "fail"
    # indefinite empty array -> definite
    if run(path, "9fff") != "80":
        return "fail"
    # indefinite map {"a":1,"b":2} -> definite
    if run(path, "bf616101616202ff") != "a2616101616202":
        return "fail"
    # indefinite byte string -> definite
    if run(path, "5f42010243030405ff") != "450102030405":
        return "fail"
    return "pass"


def check_map_key_ordering(path):
    """Test that map keys are sorted by bytewise lexicographic order."""
    # {1000:1, "z":2} — bytewise 0x1903e8 < 0x617a, order preserved
    # Length-first would swap (2-byte "z" before 3-byte 1000)
    if run(path, "a21903e801617a02") != "a21903e801617a02":
        return "fail"
    # Reversed input must be reordered
    if run(path, "a2617a021903e801") != "a21903e801617a02":
        return "fail"
    # RFC 8-key example
    inp = "a8f4008120018118640262616103617a0420051864060a07"
    exp = "a80a071864062005617a046261610381186402812001f400"
    if run(path, inp) != exp:
        return "fail"
    return "pass"


# Run the audit
report = {}
for name, path in sorted(ENCODERS.items()):
    print(f"Auditing encoder: {name} ({path})")
    report[name] = {
        "preferred_int_args": check_preferred_int_args(path),
        "preferred_float_nan": check_preferred_float_nan(path),
        "preferred_float_neg_zero": check_preferred_float_neg_zero(path),
        "preferred_float_shortest": check_preferred_float_shortest(path),
        "no_indefinite_length": check_no_indefinite_length(path),
        "map_key_ordering": check_map_key_ordering(path),
    }
    failures = [r for r, v in report[name].items() if v == "fail"]
    print(f"  Failures: {failures if failures else 'none'}")

with open("/app/conformance_report.json", "w") as f:
    json.dump(report, f, indent=2, sort_keys=True)

print(f"\nConformance report written to /app/conformance_report.json")
print(json.dumps(report, indent=2, sort_keys=True))
