#!/usr/bin/env python3
"""
Tests for the WebAssembly Component Model canonical ABI layout engine.

Verifies size/alignment computation, flat representation, field offsets,
lift/lower operations, MAX_FLAT_PARAMS threshold detection, flatten_functype
core signature computation, and store/load list serialization per the
canonical ABI specification.

"""

import sys
import struct
import pytest

sys.path.insert(0, '/app')
import cabi

TYPES = cabi.load_types('/app/types.json')


# ---------------------------------------------------------------------------
# Size and alignment
# ---------------------------------------------------------------------------

class TestSizeAlignment:
    """Test canonical ABI size and alignment for all type kinds."""

    @pytest.mark.parametrize("type_ref,expected_size,expected_align", [
        # Primitives
        ("bool", 1, 1),
        ("u8", 1, 1),
        ("s8", 1, 1),
        ("u16", 2, 2),
        ("s16", 2, 2),
        ("u32", 4, 4),
        ("s32", 4, 4),
        ("u64", 8, 8),
        ("s64", 8, 8),
        ("f32", 4, 4),
        ("f64", 8, 8),
        ("char", 4, 4),
        ("string", 8, 4),
        # Named types
        ("point2d", 8, 4),
        ("rgba", 4, 1),
        ("mixed-align", 24, 8),
        ("direction", 1, 1),
        ("small-flags", 1, 1),
        ("medium-flags", 2, 2),
        ("large-flags", 8, 4),
        ("error-info", 12, 4),
        ("maybe-value", 16, 8),
        ("op-result", 16, 4),
        ("pair", 16, 8),
        ("nested-record", 24, 8),
        ("nested-opt", 24, 8),
        ("complex-variant", 24, 8),
        ("wide-record", 72, 8),
        ("mega-record", 68, 4),
        ("message", 24, 8),
        ("point-list", 8, 4),
    ])
    def test_size_and_alignment(self, type_ref, expected_size, expected_align):
        assert cabi.size_of(TYPES, type_ref) == expected_size
        assert cabi.align_of(TYPES, type_ref) == expected_align

    def test_inline_record_size(self):
        """Inline record type (not in types.json)."""
        inline = {"kind": "record", "fields": [["a", "u8"], ["b", "u64"]]}
        # a at 0 (size 1), b at align_to(1,8)=8 (size 8) => total align_to(16,8)=16
        assert cabi.size_of(TYPES, inline) == 16
        assert cabi.align_of(TYPES, inline) == 8

    def test_inline_option_size(self):
        """Inline option type."""
        inline = {"kind": "option", "type": "u32"}
        # variant{none, some(u32)}: disc=1, a=4, s=4
        # size = align_to(align_to(1,4)+4, max(1,4)) = align_to(8,4)=8
        assert cabi.size_of(TYPES, inline) == 8
        assert cabi.align_of(TYPES, inline) == 4

    def test_inline_result_size(self):
        """Inline result type with different-aligned ok/error."""
        inline = {"kind": "result", "ok": "u8", "error": "f64"}
        # variant{ok(u8), error(f64)}: disc=1, s=max(1,8)=8, a=max(1,8)=8
        # size = align_to(align_to(1,8)+8, 8) = align_to(16,8)=16
        assert cabi.size_of(TYPES, inline) == 16
        assert cabi.align_of(TYPES, inline) == 8

    def test_empty_flags_size(self):
        """Flags with zero labels."""
        inline = {"kind": "flags", "labels": []}
        assert cabi.size_of(TYPES, inline) == 0

    def test_single_case_variant_size(self):
        """Variant with exactly one case."""
        inline = {"kind": "variant", "cases": [["only", "u32"]]}
        # disc=1 (1 case), s=4, a=4
        # size = align_to(align_to(1,4)+4, 4) = align_to(8,4)=8
        assert cabi.size_of(TYPES, inline) == 8


# ---------------------------------------------------------------------------
# Field offsets
# ---------------------------------------------------------------------------

class TestFieldOffsets:
    """Test field offset computation for records and tuples."""

    @pytest.mark.parametrize("type_ref,expected", [
        ("point2d", {"x": 0, "y": 4}),
        ("rgba", {"r": 0, "g": 1, "b": 2, "a": 3}),
        ("mixed-align", {"flag": 0, "value": 8, "tag": 16}),
        ("pair", {"0": 0, "1": 8}),
        ("nested-record", {"id": 0, "pos": 8, "color": 16, "active": 20}),
        ("message", {"priority": 0, "text": 4, "timestamp": 16}),
    ])
    def test_offsets(self, type_ref, expected):
        assert cabi.field_offsets(TYPES, type_ref) == expected

    def test_wide_record_offsets(self):
        offsets = cabi.field_offsets(TYPES, "wide-record")
        for i, field in enumerate("abcdefghi"):
            assert offsets[field] == i * 8

    def test_mega_record_offsets(self):
        offsets = cabi.field_offsets(TYPES, "mega-record")
        for i in range(17):
            assert offsets[f"f{i}"] == i * 4


# ---------------------------------------------------------------------------
# Flat representation
# ---------------------------------------------------------------------------

class TestFlatten:
    """Test flat core wasm valtype decomposition."""

    @pytest.mark.parametrize("type_ref,expected", [
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
        ("nested-record", ["i64", "f32", "f32", "i32", "i32", "i32", "i32", "i32"]),
        ("nested-opt", ["i32", "i32", "f64"]),
        ("complex-variant", ["i32", "i64", "f64"]),
        ("wide-record", ["f64"] * 9),
        ("mega-record", ["i32"] * 17),
        ("message", ["i32", "i32", "i32", "i64"]),
        ("point-list", ["i32", "i32"]),
    ])
    def test_flatten(self, type_ref, expected):
        assert cabi.flatten_type(TYPES, type_ref) == expected

    def test_flatten_primitive_string(self):
        assert cabi.flatten_type(TYPES, "string") == ["i32", "i32"]

    def test_flatten_primitive_bool(self):
        assert cabi.flatten_type(TYPES, "bool") == ["i32"]

    def test_flatten_primitive_u64(self):
        assert cabi.flatten_type(TYPES, "u64") == ["i64"]

    def test_flatten_variant_join_i32_f32(self):
        """Verify join(i32, f32) = i32 (the special case)."""
        # error-info has cases: none(), code(u32->i32), detail(point2d->f32,f32)
        # At index 0: join(i32, f32) = i32
        flat = cabi.flatten_type(TYPES, "error-info")
        assert flat == ["i32", "i32", "f32"]

    def test_flatten_variant_join_mixed(self):
        """Verify join across many types falls back to i64."""
        # complex-variant index 0: i32, i32, i32, f64, i32 -> join = i64
        flat = cabi.flatten_type(TYPES, "complex-variant")
        assert flat[1] == "i64"  # the joined payload[0]


# ---------------------------------------------------------------------------
# MAX_FLAT_PARAMS threshold
# ---------------------------------------------------------------------------

class TestExceedsFlatLimit:
    """Test MAX_FLAT_PARAMS (16) detection."""

    def test_mega_record_exceeds(self):
        assert cabi.exceeds_max_flat_params(TYPES, "mega-record") is True

    def test_wide_record_does_not_exceed(self):
        assert cabi.exceeds_max_flat_params(TYPES, "wide-record") is False

    def test_point2d_does_not_exceed(self):
        assert cabi.exceeds_max_flat_params(TYPES, "point2d") is False

    def test_nested_record_does_not_exceed(self):
        assert cabi.exceeds_max_flat_params(TYPES, "nested-record") is False

    def test_complex_variant_does_not_exceed(self):
        assert cabi.exceeds_max_flat_params(TYPES, "complex-variant") is False


# ---------------------------------------------------------------------------
# Lift from byte buffers
# ---------------------------------------------------------------------------

class TestLift:
    """Test lifting values from byte buffers."""

    def test_lift_point2d(self):
        buf = struct.pack('<ff', 1.5, -2.25)
        result = cabi.lift(TYPES, "point2d", buf)
        assert result == {"x": 1.5, "y": -2.25}

    def test_lift_rgba(self):
        buf = bytes([255, 128, 0, 200])
        result = cabi.lift(TYPES, "rgba", buf)
        assert result == {"r": 255, "g": 128, "b": 0, "a": 200}

    def test_lift_mixed_align(self):
        buf = bytearray(24)
        buf[0] = 1  # flag = True
        struct.pack_into('<d', buf, 8, 3.0)
        struct.pack_into('<H', buf, 16, 1000)
        result = cabi.lift(TYPES, "mixed-align", bytes(buf))
        assert result == {"flag": True, "value": 3.0, "tag": 1000}

    def test_lift_direction(self):
        assert cabi.lift(TYPES, "direction", b'\x00') == "north"
        assert cabi.lift(TYPES, "direction", b'\x02') == "south"
        assert cabi.lift(TYPES, "direction", b'\x03') == "west"

    def test_lift_small_flags(self):
        assert cabi.lift(TYPES, "small-flags", b'\x15') == 21

    def test_lift_medium_flags(self):
        buf = struct.pack('<H', 0x0AAA)
        assert cabi.lift(TYPES, "medium-flags", buf) == 0x0AAA

    def test_lift_large_flags(self):
        buf = struct.pack('<II', 1, 1)
        result = cabi.lift(TYPES, "large-flags", buf)
        assert result == (1 | (1 << 32))

    def test_lift_error_info_none(self):
        buf = b'\x00' + b'\x00' * 11
        result = cabi.lift(TYPES, "error-info", buf)
        assert result == ("none", None)

    def test_lift_error_info_code(self):
        buf = bytearray(12)
        buf[0] = 1
        struct.pack_into('<I', buf, 4, 404)
        result = cabi.lift(TYPES, "error-info", bytes(buf))
        assert result == ("code", 404)

    def test_lift_error_info_detail(self):
        buf = bytearray(12)
        buf[0] = 2
        struct.pack_into('<f', buf, 4, 1.0)
        struct.pack_into('<f', buf, 8, 2.0)
        result = cabi.lift(TYPES, "error-info", bytes(buf))
        assert result == ("detail", {"x": 1.0, "y": 2.0})

    def test_lift_maybe_value_none(self):
        buf = b'\x00' * 16
        result = cabi.lift(TYPES, "maybe-value", buf)
        assert result == ("none", None)

    def test_lift_maybe_value_some(self):
        buf = bytearray(16)
        buf[0] = 1
        struct.pack_into('<d', buf, 8, 2.5)
        result = cabi.lift(TYPES, "maybe-value", bytes(buf))
        assert result == ("some", 2.5)

    def test_lift_pair(self):
        buf = bytearray(16)
        struct.pack_into('<I', buf, 0, 42)
        struct.pack_into('<d', buf, 8, 3.0)
        result = cabi.lift(TYPES, "pair", bytes(buf))
        assert result == (42, 3.0)

    def test_lift_op_result_ok(self):
        buf = bytearray(16)
        buf[0] = 0  # ok
        struct.pack_into('<I', buf, 4, 42)
        result = cabi.lift(TYPES, "op-result", buf)
        assert result == ("ok", 42)

    def test_lift_op_result_error_code(self):
        """Nested variant lift: result<u32, variant{..., code(u32), ...}>."""
        buf = bytearray(16)
        buf[0] = 1   # outer disc: error
        buf[4] = 1   # inner disc: code
        struct.pack_into('<I', buf, 8, 404)
        result = cabi.lift(TYPES, "op-result", bytes(buf))
        assert result == ("error", ("code", 404))

    def test_lift_op_result_error_detail(self):
        """Triple-nested lift: result -> variant -> record."""
        buf = bytearray(16)
        buf[0] = 1   # outer disc: error
        buf[4] = 2   # inner disc: detail
        struct.pack_into('<f', buf, 8, 3.0)
        struct.pack_into('<f', buf, 12, 4.0)
        result = cabi.lift(TYPES, "op-result", bytes(buf))
        assert result == ("error", ("detail", {"x": 3.0, "y": 4.0}))

    def test_lift_nested_opt_none(self):
        buf = b'\x00' * 24
        result = cabi.lift(TYPES, "nested-opt", buf)
        assert result == ("none", None)

    def test_lift_nested_opt_some_none(self):
        """Nested option: Some(None) is distinguishable from None."""
        buf = bytearray(24)
        buf[0] = 1  # outer: some
        buf[8] = 0  # inner: none
        result = cabi.lift(TYPES, "nested-opt", bytes(buf))
        assert result == ("some", ("none", None))

    def test_lift_nested_opt_some_some(self):
        buf = bytearray(24)
        buf[0] = 1   # outer: some
        buf[8] = 1   # inner: some
        struct.pack_into('<d', buf, 16, 42.0)
        result = cabi.lift(TYPES, "nested-opt", bytes(buf))
        assert result == ("some", ("some", 42.0))

    def test_lift_complex_variant_empty(self):
        buf = b'\x00' * 24
        result = cabi.lift(TYPES, "complex-variant", buf)
        assert result == ("empty", None)

    def test_lift_complex_variant_flag(self):
        buf = bytearray(24)
        buf[0] = 1   # flag
        buf[8] = 1   # True
        result = cabi.lift(TYPES, "complex-variant", bytes(buf))
        assert result == ("flag", True)

    def test_lift_complex_variant_large(self):
        buf = bytearray(24)
        buf[0] = 4  # large
        struct.pack_into('<d', buf, 8, 1.5)
        result = cabi.lift(TYPES, "complex-variant", bytes(buf))
        assert result == ("large", 1.5)

    def test_lift_complex_variant_compound(self):
        buf = bytearray(24)
        buf[0] = 5  # compound
        struct.pack_into('<I', buf, 8, 100)
        struct.pack_into('<d', buf, 16, 2.5)
        result = cabi.lift(TYPES, "complex-variant", bytes(buf))
        assert result == ("compound", (100, 2.5))

    def test_lift_nested_record(self):
        buf = bytearray(24)
        struct.pack_into('<Q', buf, 0, 1000000)
        struct.pack_into('<f', buf, 8, 5.0)
        struct.pack_into('<f', buf, 12, 10.0)
        buf[16] = 255; buf[17] = 0; buf[18] = 128; buf[19] = 255
        buf[20] = 1  # active
        result = cabi.lift(TYPES, "nested-record", bytes(buf))
        assert result == {
            "id": 1000000,
            "pos": {"x": 5.0, "y": 10.0},
            "color": {"r": 255, "g": 0, "b": 128, "a": 255},
            "active": True,
        }

    def test_lift_bool_primitives(self):
        assert cabi.lift(TYPES, "bool", b'\x00') is False
        assert cabi.lift(TYPES, "bool", b'\x01') is True
        assert cabi.lift(TYPES, "bool", b'\xff') is True  # nonzero = True

    def test_lift_signed_integers(self):
        buf = struct.pack('<b', -42)
        assert cabi.lift(TYPES, "s8", buf) == -42
        buf = struct.pack('<h', -1000)
        assert cabi.lift(TYPES, "s16", buf) == -1000
        buf = struct.pack('<i', -100000)
        assert cabi.lift(TYPES, "s32", buf) == -100000
        buf = struct.pack('<q', -10**15)
        assert cabi.lift(TYPES, "s64", buf) == -10**15

    def test_lift_char(self):
        buf = struct.pack('<I', 65)
        assert cabi.lift(TYPES, "char", buf) == 'A'
        buf = struct.pack('<I', 8364)
        assert cabi.lift(TYPES, "char", buf) == '\u20ac'  # euro sign

    def test_lift_string(self):
        buf = struct.pack('<II', 1024, 5)
        result = cabi.lift(TYPES, "string", buf)
        assert result == (1024, 5)

    def test_lift_list(self):
        buf = struct.pack('<II', 2048, 100)
        result = cabi.lift(TYPES, "point-list", buf)
        assert result == (2048, 100)

    def test_lift_at_nonzero_offset(self):
        """Verify lift works with non-zero offset."""
        prefix = b'\xde\xad' * 10  # 20 garbage bytes
        buf = prefix + struct.pack('<ff', 7.0, 8.0)
        result = cabi.lift(TYPES, "point2d", buf, 20)
        assert result == {"x": 7.0, "y": 8.0}


# ---------------------------------------------------------------------------
# Lower to byte buffers
# ---------------------------------------------------------------------------

class TestLower:
    """Test lowering values to byte buffers."""

    def test_lower_point2d(self):
        result = cabi.lower(TYPES, "point2d", {"x": 1.5, "y": -2.25})
        expected = struct.pack('<ff', 1.5, -2.25)
        assert result == expected

    def test_lower_rgba(self):
        result = cabi.lower(TYPES, "rgba", {"r": 255, "g": 128, "b": 0, "a": 200})
        assert result == bytes([255, 128, 0, 200])

    def test_lower_direction(self):
        result = cabi.lower(TYPES, "direction", "south")
        assert result == b'\x02'

    def test_lower_small_flags(self):
        result = cabi.lower(TYPES, "small-flags", 21)
        assert result == b'\x15'

    def test_lower_large_flags(self):
        val = (1 << 0) | (1 << 32)
        result = cabi.lower(TYPES, "large-flags", val)
        assert result == struct.pack('<II', 1, 1)

    def test_lower_error_info_none(self):
        result = cabi.lower(TYPES, "error-info", ("none", None))
        assert len(result) == 12
        assert result[0] == 0  # disc

    def test_lower_error_info_code(self):
        result = cabi.lower(TYPES, "error-info", ("code", 404))
        assert len(result) == 12
        assert result[0] == 1  # disc
        assert struct.unpack_from('<I', result, 4)[0] == 404

    def test_lower_pair(self):
        result = cabi.lower(TYPES, "pair", (42, 3.0))
        assert len(result) == 16
        assert struct.unpack_from('<I', result, 0)[0] == 42
        assert struct.unpack_from('<d', result, 8)[0] == 3.0

    def test_lower_primitives(self):
        assert cabi.lower(TYPES, "bool", True) == b'\x01'
        assert cabi.lower(TYPES, "bool", False) == b'\x00'
        assert cabi.lower(TYPES, "u8", 255) == b'\xff'
        assert cabi.lower(TYPES, "char", 'A') == struct.pack('<I', 65)
        assert cabi.lower(TYPES, "s32", -1) == struct.pack('<i', -1)

    def test_lower_string(self):
        result = cabi.lower(TYPES, "string", (1024, 5))
        assert result == struct.pack('<II', 1024, 5)

    def test_lower_produces_correct_size(self):
        """Every lower call produces exactly size_of bytes."""
        test_values = [
            ("point2d", {"x": 0.0, "y": 0.0}),
            ("rgba", {"r": 0, "g": 0, "b": 0, "a": 0}),
            ("mixed-align", {"flag": False, "value": 0.0, "tag": 0}),
            ("direction", "north"),
            ("small-flags", 0),
            ("medium-flags", 0),
            ("large-flags", 0),
            ("error-info", ("none", None)),
            ("maybe-value", ("none", None)),
            ("op-result", ("ok", 0)),
            ("pair", (0, 0.0)),
            ("nested-opt", ("none", None)),
            ("complex-variant", ("empty", None)),
        ]
        for type_ref, val in test_values:
            result = cabi.lower(TYPES, type_ref, val)
            expected_size = cabi.size_of(TYPES, type_ref)
            assert len(result) == expected_size, \
                f"{type_ref}: got {len(result)} bytes, expected {expected_size}"


# ---------------------------------------------------------------------------
# Round-trip lift/lower
# ---------------------------------------------------------------------------

class TestRoundTrip:
    """Verify lower->lift round-trip preserves values exactly."""

    @pytest.mark.parametrize("type_ref,value", [
        ("point2d", {"x": 1.5, "y": -2.25}),
        ("rgba", {"r": 255, "g": 128, "b": 0, "a": 200}),
        ("mixed-align", {"flag": True, "value": 3.0, "tag": 1000}),
        ("direction", "north"),
        ("direction", "west"),
        ("small-flags", 21),
        ("medium-flags", 0x0AAA),
        ("large-flags", (1 << 0) | (1 << 32)),
        ("error-info", ("none", None)),
        ("error-info", ("code", 404)),
        ("error-info", ("detail", {"x": 1.0, "y": 2.0})),
        ("maybe-value", ("none", None)),
        ("maybe-value", ("some", 2.5)),
        ("op-result", ("ok", 42)),
        ("op-result", ("error", ("code", 404))),
        ("op-result", ("error", ("detail", {"x": 3.0, "y": 4.0}))),
        ("pair", (42, 3.0)),
        ("nested-opt", ("none", None)),
        ("nested-opt", ("some", ("none", None))),
        ("nested-opt", ("some", ("some", 42.0))),
        ("complex-variant", ("empty", None)),
        ("complex-variant", ("flag", True)),
        ("complex-variant", ("small", 7)),
        ("complex-variant", ("medium", 12345)),
        ("complex-variant", ("large", 1.5)),
        ("complex-variant", ("compound", (100, 2.5))),
        ("nested-record", {
            "id": 1000000,
            "pos": {"x": 5.0, "y": 10.0},
            "color": {"r": 255, "g": 0, "b": 128, "a": 255},
            "active": True,
        }),
    ])
    def test_round_trip(self, type_ref, value):
        lowered = cabi.lower(TYPES, type_ref, value)
        lifted = cabi.lift(TYPES, type_ref, lowered)
        assert lifted == value, f"Round-trip failed for {type_ref}: {value} -> {lowered.hex()} -> {lifted}"

    def test_round_trip_variant_padding_is_zeroed(self):
        """Unused payload bytes should be zero after lower."""
        # error-info "none" has 12 bytes, disc at 0, payload area unused
        result = cabi.lower(TYPES, "error-info", ("none", None))
        assert result == b'\x00' * 12

        # maybe-value "none" has 16 bytes
        result = cabi.lower(TYPES, "maybe-value", ("none", None))
        assert result == b'\x00' * 16

    def test_round_trip_mixed_align_padding(self):
        """Alignment padding bytes should be zero."""
        result = cabi.lower(TYPES, "mixed-align", {"flag": True, "value": 3.0, "tag": 1000})
        # Bytes 1-7 should be zero (padding between flag and value)
        assert result[1:8] == b'\x00' * 7
        # Bytes 18-23 should be zero (trailing padding)
        assert result[18:24] == b'\x00' * 6


# ---------------------------------------------------------------------------
# Byte-exact verification
# ---------------------------------------------------------------------------

class TestExactBytes:
    """Verify specific byte sequences match the canonical ABI encoding."""

    def test_point2d_exact_bytes(self):
        result = cabi.lower(TYPES, "point2d", {"x": 1.5, "y": -2.25})
        assert result == bytes.fromhex("0000c03f000010c0")

    def test_error_info_code_exact_bytes(self):
        result = cabi.lower(TYPES, "error-info", ("code", 404))
        assert result == bytes.fromhex("010000009401000000000000")

    def test_op_result_nested_exact_bytes(self):
        """Exact bytes for op-result error(code(404))."""
        result = cabi.lower(TYPES, "op-result", ("error", ("code", 404)))
        assert result == bytes.fromhex("01000000010000009401000000000000")

    def test_nested_opt_some_some_exact_bytes(self):
        """Exact bytes for option<option<f64>> = Some(Some(42.0))."""
        result = cabi.lower(TYPES, "nested-opt", ("some", ("some", 42.0)))
        assert result == bytes.fromhex("010000000000000001000000000000000000000000004540")

    def test_complex_variant_compound_exact_bytes(self):
        result = cabi.lower(TYPES, "complex-variant", ("compound", (100, 2.5)))
        assert result == bytes.fromhex("050000000000000064000000000000000000000000000440")


# ---------------------------------------------------------------------------
# Flatten functype
# ---------------------------------------------------------------------------

class TestFlattenFunctype:
    """Test core wasm function signature computation with MAX_FLAT thresholds."""

    def test_simple_func(self):
        """func(u32) -> u32: both fit in single flat value."""
        params, results = cabi.flatten_functype(TYPES, ["u32"], ["u32"])
        assert params == ["i32"]
        assert results == ["i32"]

    def test_record_param(self):
        """func(point2d) -> u32: record flattens to multiple valtypes."""
        params, results = cabi.flatten_functype(TYPES, ["point2d"], ["u32"])
        assert params == ["f32", "f32"]
        assert results == ["i32"]

    def test_multi_result_spill(self):
        """func(u32) -> point2d: 2 flat results > MAX_FLAT_RESULTS(1), spill."""
        params, results = cabi.flatten_functype(TYPES, ["u32"], ["point2d"])
        assert params == ["i32"]
        assert results == ["i32"]  # spilled to pointer

    def test_params_within_limit(self):
        """func(wide-record) -> u32: 9 flat params <= 16, stays flat."""
        params, results = cabi.flatten_functype(TYPES, ["wide-record"], ["u32"])
        assert params == ["f64"] * 9

    def test_params_exceed_limit(self):
        """func(mega-record) -> u32: 17 flat params > 16, spill."""
        params, results = cabi.flatten_functype(TYPES, ["mega-record"], ["u32"])
        assert params == ["i32"]

    def test_multiple_params_concat(self):
        """Multiple params concatenate their flat representations."""
        params, results = cabi.flatten_functype(TYPES, ["point2d", "rgba"], ["u32"])
        assert params == ["f32", "f32", "i32", "i32", "i32", "i32"]

    def test_both_spill(self):
        """Both params and results exceed flat limits."""
        params, results = cabi.flatten_functype(TYPES, ["mega-record"], ["point2d"])
        assert params == ["i32"]
        assert results == ["i32"]

    def test_empty_func(self):
        """func() -> (): no params, no results."""
        params, results = cabi.flatten_functype(TYPES, [], [])
        assert params == []
        assert results == []

    def test_params_at_exact_limit(self):
        """Exactly MAX_FLAT_PARAMS (16) params should NOT spill."""
        # 4 * rgba = 4 * 4 flat values = 16
        params, results = cabi.flatten_functype(
            TYPES, ["rgba", "rgba", "rgba", "rgba"], ["u32"]
        )
        assert len(params) == 16
        assert params == ["i32"] * 16

    def test_params_one_over_limit(self):
        """MAX_FLAT_PARAMS + 1 params should spill."""
        # 4 * rgba + u32 = 17 flat params
        params, results = cabi.flatten_functype(
            TYPES, ["rgba", "rgba", "rgba", "rgba", "u32"], ["u32"]
        )
        assert params == ["i32"]

    def test_variant_param(self):
        """Variant types flatten correctly in function signatures."""
        params, results = cabi.flatten_functype(TYPES, ["error-info"], ["u32"])
        assert params == ["i32", "i32", "f32"]

    def test_single_result_stays_flat(self):
        """A single flat result does not spill."""
        params, results = cabi.flatten_functype(TYPES, [], ["u32"])
        assert results == ["i32"]

    def test_no_results(self):
        """Function with params but no results."""
        params, results = cabi.flatten_functype(TYPES, ["u32"], [])
        assert params == ["i32"]
        assert results == []


# ---------------------------------------------------------------------------
# Store list
# ---------------------------------------------------------------------------

class TestStoreList:
    """Test canonical ABI list serialization."""

    def test_store_point2d_list(self):
        values = [{"x": 1.0, "y": 2.0}, {"x": 3.0, "y": 4.0}]
        buf = cabi.store_list(TYPES, "point2d", values)
        assert len(buf) == 16  # 2 * 8 bytes
        assert struct.unpack_from('<ff', buf, 0) == (1.0, 2.0)
        assert struct.unpack_from('<ff', buf, 8) == (3.0, 4.0)

    def test_store_u8_list(self):
        values = [1, 2, 3, 4, 5]
        buf = cabi.store_list(TYPES, "u8", values)
        assert len(buf) == 5
        assert buf == bytes([1, 2, 3, 4, 5])

    def test_store_empty_list(self):
        buf = cabi.store_list(TYPES, "point2d", [])
        assert buf == b''

    def test_store_mixed_align_stride(self):
        """Elements with alignment padding maintain correct stride."""
        values = [
            {"flag": True, "value": 1.0, "tag": 100},
            {"flag": False, "value": 2.0, "tag": 200},
        ]
        buf = cabi.store_list(TYPES, "mixed-align", values)
        assert len(buf) == 48  # 2 * 24 bytes (stride=24 due to trailing alignment)
        # First element at offset 0
        assert buf[0] == 1  # flag=True
        assert struct.unpack_from('<d', buf, 8)[0] == 1.0
        assert struct.unpack_from('<H', buf, 16)[0] == 100
        # Second element at offset 24
        assert buf[24] == 0  # flag=False
        assert struct.unpack_from('<d', buf, 32)[0] == 2.0
        assert struct.unpack_from('<H', buf, 40)[0] == 200

    def test_store_f64_list(self):
        values = [1.5, -2.25, 0.0]
        buf = cabi.store_list(TYPES, "f64", values)
        assert len(buf) == 24
        for i, v in enumerate(values):
            assert struct.unpack_from('<d', buf, i * 8)[0] == v

    def test_store_variant_list(self):
        values = [("none", None), ("code", 404)]
        buf = cabi.store_list(TYPES, "error-info", values)
        assert len(buf) == 24  # 2 * 12
        # First: none
        assert buf[0] == 0
        # Second: code(404)
        assert buf[12] == 1
        assert struct.unpack_from('<I', buf, 16)[0] == 404

    def test_store_single_element(self):
        values = [{"x": 5.0, "y": -3.0}]
        buf = cabi.store_list(TYPES, "point2d", values)
        assert len(buf) == 8
        assert struct.unpack_from('<ff', buf, 0) == (5.0, -3.0)


# ---------------------------------------------------------------------------
# Load list
# ---------------------------------------------------------------------------

class TestLoadList:
    """Test canonical ABI list deserialization."""

    def test_load_point2d_list(self):
        buf = struct.pack('<ffff', 1.0, 2.0, 3.0, 4.0)
        result = cabi.load_list(TYPES, "point2d", buf, 2)
        assert result == [{"x": 1.0, "y": 2.0}, {"x": 3.0, "y": 4.0}]

    def test_load_u8_list(self):
        buf = bytes([10, 20, 30])
        result = cabi.load_list(TYPES, "u8", buf, 3)
        assert result == [10, 20, 30]

    def test_load_empty(self):
        result = cabi.load_list(TYPES, "point2d", b'', 0)
        assert result == []

    def test_load_f64_list(self):
        buf = struct.pack('<ddd', 1.5, -2.25, 0.0)
        result = cabi.load_list(TYPES, "f64", buf, 3)
        assert result == [1.5, -2.25, 0.0]

    def test_store_load_roundtrip_point2d(self):
        values = [{"x": 1.5, "y": -2.25}, {"x": 0.0, "y": 100.0}]
        buf = cabi.store_list(TYPES, "point2d", values)
        result = cabi.load_list(TYPES, "point2d", buf, 2)
        assert result == values

    def test_store_load_roundtrip_mixed_align(self):
        values = [
            {"flag": True, "value": 1.0, "tag": 100},
            {"flag": False, "value": 2.0, "tag": 200},
        ]
        buf = cabi.store_list(TYPES, "mixed-align", values)
        result = cabi.load_list(TYPES, "mixed-align", buf, 2)
        assert result == values

    def test_store_load_roundtrip_variant(self):
        values = [("none", None), ("code", 42), ("detail", {"x": 1.0, "y": 2.0})]
        buf = cabi.store_list(TYPES, "error-info", values)
        result = cabi.load_list(TYPES, "error-info", buf, 3)
        assert result == values

    def test_store_load_roundtrip_nested_record(self):
        values = [
            {"id": 1, "pos": {"x": 1.0, "y": 2.0},
             "color": {"r": 255, "g": 0, "b": 0, "a": 255}, "active": True},
            {"id": 2, "pos": {"x": 3.0, "y": 4.0},
             "color": {"r": 0, "g": 255, "b": 0, "a": 128}, "active": False},
        ]
        buf = cabi.store_list(TYPES, "nested-record", values)
        result = cabi.load_list(TYPES, "nested-record", buf, 2)
        assert result == values

    def test_store_load_roundtrip_direction(self):
        values = ["north", "east", "south", "west"]
        buf = cabi.store_list(TYPES, "direction", values)
        result = cabi.load_list(TYPES, "direction", buf, 4)
        assert result == values
