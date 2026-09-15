#!/usr/bin/env python3
"""
Conformance checker for the canonical ABI layout engine.
Compares engine output against reference values from a known-correct
implementation of the WebAssembly Component Model canonical ABI.

"""

import sys
import struct
import traceback

sys.path.insert(0, '/app')
import cabi

TYPES = cabi.load_types('/app/types.json')

_pass = 0
_fail = 0
_error = 0


def check(label, actual, expected):
    global _pass, _fail
    if actual == expected:
        _pass += 1
    else:
        _fail += 1
        print(f"  FAIL: {label}")
        print(f"    expected: {repr(expected)}")
        print(f"    actual:   {repr(actual)}")


def check_bytes(label, actual_bytes, expected_hex):
    global _pass, _fail
    expected_bytes = bytes.fromhex(expected_hex)
    if actual_bytes == expected_bytes:
        _pass += 1
    else:
        _fail += 1
        print(f"  FAIL: {label}")
        print(f"    expected hex: {expected_hex}")
        print(f"    actual hex:   {actual_bytes.hex()}")
        print(f"    expected len: {len(expected_bytes)}")
        print(f"    actual len:   {len(actual_bytes)}")


def safe_check(label, fn, expected):
    global _error
    try:
        actual = fn()
        check(label, actual, expected)
    except Exception as e:
        _error += 1
        print(f"  ERROR: {label}")
        print(f"    exception: {e}")


def section(name):
    print(f"\n== {name} ==")


# ---------------------------------------------------------------
# Size and alignment
# ---------------------------------------------------------------
section("Size Conformance")
size_refs = [
    ("bool", 1), ("u8", 1), ("u16", 2), ("u32", 4), ("u64", 8),
    ("s8", 1), ("s16", 2), ("s32", 4), ("s64", 8),
    ("f32", 4), ("f64", 8), ("char", 4), ("string", 8),
    ("point2d", 8), ("rgba", 4), ("mixed-align", 24),
    ("direction", 1), ("small-flags", 1), ("medium-flags", 2),
    ("large-flags", 8), ("error-info", 12), ("maybe-value", 16),
    ("op-result", 16), ("pair", 16), ("nested-record", 24),
    ("nested-opt", 24), ("complex-variant", 24),
    ("wide-record", 72), ("mega-record", 68),
    ("message", 24), ("point-list", 8),
]
for type_ref, expected_size in size_refs:
    safe_check(
        f"size_of({type_ref})",
        lambda t=type_ref: cabi.size_of(TYPES, t),
        expected_size,
    )

section("Alignment Conformance")
align_refs = [
    ("point2d", 4), ("rgba", 1), ("mixed-align", 8),
    ("direction", 1), ("small-flags", 1), ("medium-flags", 2),
    ("large-flags", 4), ("error-info", 4), ("maybe-value", 8),
    ("op-result", 4), ("pair", 8), ("nested-record", 8),
    ("nested-opt", 8), ("complex-variant", 8),
    ("wide-record", 8), ("mega-record", 4),
    ("message", 8), ("point-list", 4),
]
for type_ref, expected_align in align_refs:
    safe_check(
        f"align_of({type_ref})",
        lambda t=type_ref: cabi.align_of(TYPES, t),
        expected_align,
    )

# ---------------------------------------------------------------
# Flat representation
# ---------------------------------------------------------------
section("Flat Representation Conformance")
flat_refs = [
    ("point2d", ["f32", "f32"]),
    ("rgba", ["i32", "i32", "i32", "i32"]),
    ("mixed-align", ["i32", "f64", "i32"]),
    ("direction", ["i32"]),
    ("small-flags", ["i32"]),
    ("medium-flags", ["i32"]),
    ("large-flags", ["i32", "i32"]),
    ("error-info", ["i32", "i32", "f32"]),
    ("maybe-value", ["i32", "f64"]),
    ("op-result", ["i32", "i32", "i32", "f32"]),
    ("pair", ["i32", "f64"]),
    ("nested-opt", ["i32", "i32", "f64"]),
    ("complex-variant", ["i32", "i64", "f64"]),
    ("wide-record", ["f64"] * 9),
    ("mega-record", ["i32"] * 17),
    ("message", ["i32", "i32", "i32", "i64"]),
    ("point-list", ["i32", "i32"]),
]
for type_ref, expected in flat_refs:
    safe_check(
        f"flatten({type_ref})",
        lambda t=type_ref: cabi.flatten_type(TYPES, t),
        expected,
    )

# ---------------------------------------------------------------
# Field offsets
# ---------------------------------------------------------------
section("Field Offset Conformance")
offset_refs = [
    ("point2d", {"x": 0, "y": 4}),
    ("rgba", {"r": 0, "g": 1, "b": 2, "a": 3}),
    ("mixed-align", {"flag": 0, "value": 8, "tag": 16}),
    ("pair", {"0": 0, "1": 8}),
    ("nested-record", {"id": 0, "pos": 8, "color": 16, "active": 20}),
    ("message", {"priority": 0, "text": 4, "timestamp": 16}),
]
for type_ref, expected in offset_refs:
    safe_check(
        f"field_offsets({type_ref})",
        lambda t=type_ref: cabi.field_offsets(TYPES, t),
        expected,
    )

# ---------------------------------------------------------------
# Lift from byte buffers
# ---------------------------------------------------------------
section("Lift Conformance")

# point2d
buf = struct.pack('<ff', 1.5, -2.25)
safe_check("lift(point2d)", lambda: cabi.lift(TYPES, "point2d", buf), {"x": 1.5, "y": -2.25})

# rgba
buf = bytes([255, 128, 0, 200])
safe_check("lift(rgba)", lambda: cabi.lift(TYPES, "rgba", buf), {"r": 255, "g": 128, "b": 0, "a": 200})

# mixed-align
buf = bytearray(24)
buf[0] = 1
struct.pack_into('<d', buf, 8, 3.0)
struct.pack_into('<H', buf, 16, 1000)
buf = bytes(buf)
safe_check("lift(mixed-align)", lambda: cabi.lift(TYPES, "mixed-align", buf), {"flag": True, "value": 3.0, "tag": 1000})

# direction enum
safe_check("lift(direction, north)", lambda: cabi.lift(TYPES, "direction", b'\x00'), "north")
safe_check("lift(direction, south)", lambda: cabi.lift(TYPES, "direction", b'\x02'), "south")

# error-info code(404)
buf = bytearray(12)
buf[0] = 1
struct.pack_into('<I', buf, 4, 404)
buf = bytes(buf)
safe_check("lift(error-info, code(404))", lambda: cabi.lift(TYPES, "error-info", buf), ("code", 404))

# error-info detail(point2d)
buf = bytearray(12)
buf[0] = 2
struct.pack_into('<f', buf, 4, 1.0)
struct.pack_into('<f', buf, 8, 2.0)
buf = bytes(buf)
safe_check("lift(error-info, detail)", lambda: cabi.lift(TYPES, "error-info", buf), ("detail", {"x": 1.0, "y": 2.0}))

# maybe-value none
safe_check("lift(maybe-value, none)", lambda: cabi.lift(TYPES, "maybe-value", b'\x00' * 16), ("none", None))

# maybe-value some(2.5)
buf = bytearray(16)
buf[0] = 1
struct.pack_into('<d', buf, 8, 2.5)
buf = bytes(buf)
safe_check("lift(maybe-value, some(2.5))", lambda: cabi.lift(TYPES, "maybe-value", buf), ("some", 2.5))

# pair
buf = bytearray(16)
struct.pack_into('<I', buf, 0, 42)
struct.pack_into('<d', buf, 8, 3.0)
buf = bytes(buf)
safe_check("lift(pair)", lambda: cabi.lift(TYPES, "pair", buf), (42, 3.0))

# bool primitives
safe_check("lift(bool, 0x00)", lambda: cabi.lift(TYPES, "bool", b'\x00'), False)
safe_check("lift(bool, 0x01)", lambda: cabi.lift(TYPES, "bool", b'\x01'), True)
safe_check("lift(bool, 0xff)", lambda: cabi.lift(TYPES, "bool", b'\xff'), True)

# signed integers
safe_check("lift(s8, -42)", lambda: cabi.lift(TYPES, "s8", struct.pack('<b', -42)), -42)
safe_check("lift(s32, -100000)", lambda: cabi.lift(TYPES, "s32", struct.pack('<i', -100000)), -100000)

# char
safe_check("lift(char, 'A')", lambda: cabi.lift(TYPES, "char", struct.pack('<I', 65)), 'A')

# ---------------------------------------------------------------
# Lower to byte buffers
# ---------------------------------------------------------------
section("Lower Conformance")

check_bytes(
    "lower(point2d)",
    cabi.lower(TYPES, "point2d", {"x": 1.5, "y": -2.25}),
    "0000c03f000010c0",
)

check_bytes(
    "lower(error-info, code(404))",
    cabi.lower(TYPES, "error-info", ("code", 404)),
    "010000009401000000000000",
)

check_bytes(
    "lower(maybe-value, some(2.5))",
    cabi.lower(TYPES, "maybe-value", ("some", 2.5)),
    "01000000000000000000000000000440",
)

check_bytes(
    "lower(direction, south)",
    cabi.lower(TYPES, "direction", "south"),
    "02",
)

check_bytes(
    "lower(mixed-align)",
    cabi.lower(TYPES, "mixed-align", {"flag": True, "value": 3.0, "tag": 1000}),
    "01000000000000000000000000000840e803000000000000",
)

# Verify lower produces correct sizes
for type_ref, val in [
    ("point2d", {"x": 0.0, "y": 0.0}),
    ("rgba", {"r": 0, "g": 0, "b": 0, "a": 0}),
    ("mixed-align", {"flag": False, "value": 0.0, "tag": 0}),
    ("direction", "north"),
    ("small-flags", 0),
    ("error-info", ("none", None)),
    ("maybe-value", ("none", None)),
    ("pair", (0, 0.0)),
]:
    safe_check(
        f"lower_size({type_ref})",
        lambda t=type_ref, v=val: len(cabi.lower(TYPES, t, v)),
        cabi.size_of(TYPES, type_ref),
    )

# ---------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------
section("Round-trip Conformance")

round_trip_cases = [
    ("point2d", {"x": 1.5, "y": -2.25}),
    ("rgba", {"r": 255, "g": 128, "b": 0, "a": 200}),
    ("mixed-align", {"flag": True, "value": 3.0, "tag": 1000}),
    ("direction", "north"),
    ("direction", "west"),
    ("error-info", ("none", None)),
    ("error-info", ("code", 404)),
    ("error-info", ("detail", {"x": 1.0, "y": 2.0})),
    ("maybe-value", ("none", None)),
    ("maybe-value", ("some", 2.5)),
    ("pair", (42, 3.0)),
    ("nested-opt", ("none", None)),
    ("nested-opt", ("some", ("none", None))),
    ("nested-opt", ("some", ("some", 42.0))),
    ("complex-variant", ("empty", None)),
    ("complex-variant", ("flag", True)),
    ("complex-variant", ("large", 1.5)),
]
for type_ref, value in round_trip_cases:
    safe_check(
        f"roundtrip({type_ref}, {repr(value)[:40]})",
        lambda t=type_ref, v=value: cabi.lift(TYPES, t, cabi.lower(TYPES, t, v)),
        value,
    )

# ---------------------------------------------------------------
# Byte-exact verification
# ---------------------------------------------------------------
section("Byte-Exact Conformance")

check_bytes(
    "exact(point2d)",
    cabi.lower(TYPES, "point2d", {"x": 1.5, "y": -2.25}),
    "0000c03f000010c0",
)

check_bytes(
    "exact(error-info, code(404))",
    cabi.lower(TYPES, "error-info", ("code", 404)),
    "010000009401000000000000",
)

check_bytes(
    "exact(nested-opt, some(some(42.0)))",
    cabi.lower(TYPES, "nested-opt", ("some", ("some", 42.0))),
    "010000000000000001000000000000000000000000004540",
)

check_bytes(
    "exact(complex-variant, compound(100, 2.5))",
    cabi.lower(TYPES, "complex-variant", ("compound", (100, 2.5))),
    "050000000000000064000000000000000000000000000440",
)

# ---------------------------------------------------------------
# Flatten functype
# ---------------------------------------------------------------
section("Flatten Functype Conformance")

safe_check(
    "flatten_functype([u32], [u32])",
    lambda: cabi.flatten_functype(TYPES, ["u32"], ["u32"]),
    (["i32"], ["i32"]),
)
safe_check(
    "flatten_functype([mega-record], [u32]) -- params spill",
    lambda: cabi.flatten_functype(TYPES, ["mega-record"], ["u32"]),
    (["i32"], ["i32"]),
)
safe_check(
    "flatten_functype([point2d], [point2d]) -- results spill",
    lambda: cabi.flatten_functype(TYPES, ["point2d"], ["point2d"]),
    (["f32", "f32"], ["i32"]),
)
safe_check(
    "flatten_functype([], []) -- empty",
    lambda: cabi.flatten_functype(TYPES, [], []),
    ([], []),
)
safe_check(
    "flatten_functype([wide-record], [u32]) -- 9 params, no spill",
    lambda: cabi.flatten_functype(TYPES, ["wide-record"], ["u32"]),
    (["f64"] * 9, ["i32"]),
)

# ---------------------------------------------------------------
# Store/Load list
# ---------------------------------------------------------------
section("Store/Load List Conformance")

test_points = [{"x": 1.0, "y": 2.0}, {"x": 3.0, "y": 4.0}]
safe_check(
    "store_list(point2d) size",
    lambda: len(cabi.store_list(TYPES, "point2d", test_points)),
    16,
)
safe_check(
    "store_load_roundtrip(point2d)",
    lambda: cabi.load_list(TYPES, "point2d",
                           cabi.store_list(TYPES, "point2d", test_points), 2),
    test_points,
)
safe_check(
    "store_list(empty)",
    lambda: cabi.store_list(TYPES, "point2d", []),
    b'',
)
safe_check(
    "load_list(empty)",
    lambda: cabi.load_list(TYPES, "point2d", b'', 0),
    [],
)

test_mixed = [
    {"flag": True, "value": 1.0, "tag": 100},
    {"flag": False, "value": 2.0, "tag": 200},
]
safe_check(
    "store_list(mixed-align) size -- stride=24",
    lambda: len(cabi.store_list(TYPES, "mixed-align", test_mixed)),
    48,
)
safe_check(
    "store_load_roundtrip(mixed-align)",
    lambda: cabi.load_list(TYPES, "mixed-align",
                           cabi.store_list(TYPES, "mixed-align", test_mixed), 2),
    test_mixed,
)

test_variants = [("none", None), ("code", 42), ("detail", {"x": 1.0, "y": 2.0})]
safe_check(
    "store_load_roundtrip(error-info)",
    lambda: cabi.load_list(TYPES, "error-info",
                           cabi.store_list(TYPES, "error-info", test_variants), 3),
    test_variants,
)

# ---------------------------------------------------------------
# Summary
# ---------------------------------------------------------------
total = _pass + _fail + _error
print(f"\n{'=' * 50}")
print(f"Results: {_pass} passed, {_fail} failed, {_error} errors")
print(f"Total: {_pass}/{total}")

if _fail == 0 and _error == 0:
    print("All conformance checks passed!")
    sys.exit(0)
else:
    print("Conformance check FAILED.")
    sys.exit(1)
