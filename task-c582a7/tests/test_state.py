
"""
Tests for defmt wire-format codec.
Verifies both encode (structured→binary) and decode (binary→text) directions,
plus round-trip consistency.
"""

import json
import os
import subprocess
import struct
import tempfile

import pytest

CODEC = "/app/codec.py"


def _run_codec(mode, data):
    """Run codec.py in the given mode with JSON data, return stdout lines."""
    fd, fname = tempfile.mkstemp(suffix=".json", dir="/tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        result = subprocess.run(
            ["python3", CODEC, mode, fname],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Codec {mode} exited {result.returncode}.\n"
            f"stderr: {result.stderr}\nstdout: {result.stdout}"
        )
        lines = result.stdout.strip().split("\n")
        return [l.strip() for l in lines if l.strip()]
    finally:
        os.unlink(fname)


def encode(table_entries, logs, timestamp=None):
    """Encode structured logs, return hex frame strings."""
    data = {
        "table": {
            "timestamp": {"format": timestamp} if timestamp else None,
            "entries": table_entries,
        },
        "logs": logs,
    }
    return _run_codec("encode", data)


def decode(table_entries, frames_hex, timestamp=None):
    """Decode hex frames, return human-readable lines."""
    data = {
        "table": {
            "timestamp": {"format": timestamp} if timestamp else None,
            "entries": table_entries,
        },
        "frames": frames_hex,
    }
    return _run_codec("decode", data)


# ===========================================================================
# Group 1: Encode -- primitive types
# ===========================================================================

class TestEncodePrimitives:
    def test_encode_no_args(self):
        entries = {"0": {"tag": "Info", "format": "Hello, world!"}}
        lines = encode(entries, [{"index": 0, "values": []}])
        assert lines[0] == "0000"

    def test_encode_u8(self):
        entries = {"0": {"tag": "Debug", "format": "x={=u8}"}}
        lines = encode(entries, [{"index": 0, "values": [42]}])
        assert lines[0] == "00002a"

    def test_encode_u16(self):
        entries = {"0": {"tag": "Info", "format": "x={=u16}"}}
        lines = encode(entries, [{"index": 0, "values": [65535]}])
        assert lines[0] == "0000ffff"

    def test_encode_u32(self):
        entries = {"0": {"tag": "Info", "format": "x={=u32}"}}
        lines = encode(entries, [{"index": 0, "values": [1]}])
        assert lines[0] == "000001000000"

    def test_encode_u64(self):
        entries = {"0": {"tag": "Info", "format": "x={=u64}"}}
        lines = encode(entries, [{"index": 0, "values": [256]}])
        assert lines[0] == "00000001000000000000"

    def test_encode_u128(self):
        entries = {"0": {"tag": "Info", "format": "x={=u128}"}}
        lines = encode(entries, [{"index": 0, "values": [1]}])
        assert lines[0] == "000001000000000000000000000000000000"

    def test_encode_i8_negative(self):
        entries = {"0": {"tag": "Info", "format": "x={=i8}"}}
        lines = encode(entries, [{"index": 0, "values": [-1]}])
        assert lines[0] == "0000ff"

    def test_encode_i16_negative(self):
        entries = {"0": {"tag": "Info", "format": "x={=i16}"}}
        lines = encode(entries, [{"index": 0, "values": [-1]}])
        assert lines[0] == "0000ffff"

    def test_encode_i32_negative(self):
        entries = {"0": {"tag": "Info", "format": "x={=i32}"}}
        lines = encode(entries, [{"index": 0, "values": [-1]}])
        assert lines[0] == "0000ffffffff"

    def test_encode_i64_negative(self):
        entries = {"0": {"tag": "Info", "format": "x={=i64}"}}
        lines = encode(entries, [{"index": 0, "values": [-1]}])
        assert lines[0] == "0000ffffffffffffffff"

    def test_encode_bool(self):
        entries = {"0": {"tag": "Info", "format": "f={=bool}"}}
        lines = encode(entries, [
            {"index": 0, "values": [True]},
            {"index": 0, "values": [False]},
        ])
        assert lines[0] == "000001"
        assert lines[1] == "000000"

    def test_encode_string(self):
        entries = {"0": {"tag": "Info", "format": "Hello {=str}"}}
        lines = encode(entries, [{"index": 0, "values": ["World"]}])
        # index=0(0000) + len=5(05000000) + "World"(576f726c64)
        assert lines[0] == "000005000000576f726c64"

    def test_encode_byte_slice(self):
        entries = {"0": {"tag": "Info", "format": "d={=[u8]}"}}
        lines = encode(entries, [{"index": 0, "values": ["172a"]}])
        # index=0(0000) + len=2(02000000) + bytes(172a)
        assert lines[0] == "000002000000172a"

    def test_encode_multiple_args(self):
        entries = {"0": {"tag": "Warn", "format": "a={=u16} b={=u32}"}}
        lines = encode(entries, [{"index": 0, "values": [65535, 1]}])
        # index=0(0000) + u16=65535(ffff) + u32=1(01000000)
        assert lines[0] == "0000ffff01000000"


# ===========================================================================
# Group 2: Encode -- compound types
# ===========================================================================

class TestEncodeCompound:
    def test_encode_nested_format(self):
        entries = {
            "0": {"tag": "Info", "format": "x={=?}"},
            "1": {"tag": "Derived", "format": "Foo {{ x: {=u8} }}"},
        }
        lines = encode(entries, [{"index": 0, "values": [
            {"format_ref": 1, "values": [42]}
        ]}])
        # index=0(0000) + sub_idx=1(0100) + u8=42(2a)
        assert lines[0] == "000001002a"

    def test_encode_format_slice(self):
        entries = {
            "0": {"tag": "Info", "format": "items={=[?]}"},
            "1": {"tag": "Prim", "format": "{=u8}"},
        }
        lines = encode(entries, [{"index": 0, "values": [
            [
                {"format_ref": 1, "values": [10]},
                {"format_ref": 1, "values": [20]},
                {"format_ref": 1, "values": [30]},
            ]
        ]}])
        # index=0(0000) + count=3(03000000) + 3x(sub_idx=1(0100) + u8)
        assert lines[0] == "0000030000000100" "0a" "0100" "14" "0100" "1e"

    def test_encode_format_sequence(self):
        """FormatSequence uses u16 LE indices with u16 LE zero terminator."""
        entries = {
            "0": {"tag": "Info", "format": "{=__internal_FormatSequence}"},
            "1": {"tag": "Derived", "format": "Foo"},
            "2": {"tag": "Derived", "format": "Bar({=u8})"},
        }
        lines = encode(entries, [{"index": 0, "values": [
            [
                {"format_ref": 1, "values": []},
                {"format_ref": 2, "values": [42]},
            ]
        ]}])
        # index=0(0000) + seq: idx=1(0100) + idx=2(0200)+u8=42(2a) + term(0000)
        assert lines[0] == "0000" "0100" "0200" "2a" "0000"

    def test_encode_format_sequence_three(self):
        """FormatSequence with three elements."""
        entries = {
            "0": {"tag": "Info", "format": "{=__internal_FormatSequence}"},
            "1": {"tag": "Derived", "format": "A"},
            "2": {"tag": "Derived", "format": "B({=u8})"},
            "3": {"tag": "Derived", "format": "C({=u16})"},
        }
        lines = encode(entries, [{"index": 0, "values": [
            [
                {"format_ref": 1, "values": []},
                {"format_ref": 2, "values": [10]},
                {"format_ref": 3, "values": [256]},
            ]
        ]}])
        # A(no args) + B(10) + C(256) + terminator
        assert lines[0] == "0000" "0100" "0200" "0a" "0300" "0001" "0000"

    def test_encode_argument_reuse(self):
        """Reused argument index: value serialized only once."""
        entries = {"0": {"tag": "Info", "format": "x={0=u8} y={0=u8}"}}
        lines = encode(entries, [{"index": 0, "values": [42]}])
        # Only one u8 byte for the reused argument
        assert lines[0] == "00002a"

    def test_encode_explicit_indices(self):
        """Explicit indices: serialized in index order regardless of format order."""
        entries = {
            "0": {"tag": "Info", "format": "a={1=u16} b={0=u8} c={1=u16}"}
        }
        lines = encode(entries, [{"index": 0, "values": [42, 65535]}])
        # arg0=u8(2a) then arg1=u16(ffff), regardless of display order
        assert lines[0] == "00002affff"

    def test_encode_bitfield_cross_byte(self):
        """Bitfield raw bytes for range 7..12: needs 2 bytes."""
        entries = {"0": {"tag": "Info", "format": "x: {0=7..12:b}"}}
        lines = encode(entries, [{"index": 0, "values": ["f0e5"]}])
        # Raw bitfield bytes: f0 e5
        assert lines[0] == "0000f0e5"

    def test_encode_bitfield_boundary(self):
        """Bitfield 0..8: boundary case, needs exactly 1 byte."""
        entries = {"0": {"tag": "Info", "format": "bf={0=0..8} val={1=u8}"}}
        lines = encode(entries, [{"index": 0, "values": ["ff", 42]}])
        # bitfield(ff) + u8=42(2a)
        assert lines[0] == "0000ff2a"

    def test_encode_bitfield_16bit(self):
        """Bitfield 0..16: needs exactly 2 bytes."""
        entries = {"0": {"tag": "Info", "format": "bf={0=0..16:#x} val={1=u8}"}}
        lines = encode(entries, [{"index": 0, "values": ["abcd", 66]}])
        # bitfield(abcd) + u8=66(42)
        assert lines[0] == "0000abcd42"

    def test_encode_timestamp(self):
        """Timestamp args serialized before message args."""
        entries = {
            "0": {"tag": "Info", "format": "x={=?}"},
            "1": {"tag": "Derived", "format": "Foo {{ x: {=u8} }}"},
        }
        lines = encode(entries, [{"index": 0,
            "values": [{"format_ref": 1, "values": [42]}],
            "timestamp_values": [2]
        }], timestamp="{=u8:us}")
        # index=0(0000) + ts_u8=2(02) + sub_idx=1(0100) + u8=42(2a)
        assert lines[0] == "00000201002a"

    def test_encode_fixed_byte_array(self):
        """Fixed-length byte array [u8;3] has no length prefix."""
        entries = {"0": {"tag": "Info", "format": "d={=[u8;3]}"}}
        lines = encode(entries, [{"index": 0, "values": ["aabbcc"]}])
        # index=0(0000) + 3 raw bytes(aabbcc) -- no length prefix
        assert lines[0] == "0000aabbcc"


# ===========================================================================
# Group 3: Decode -- basic types and display
# ===========================================================================

class TestDecodeBasic:
    def test_decode_hello(self):
        entries = {"0": {"tag": "Info", "format": "Hello, world!"}}
        lines = decode(entries, ["0000"])
        assert lines[0] == "INFO Hello, world!"

    def test_decode_u8(self):
        entries = {"0": {"tag": "Debug", "format": "The answer is {=u8}!"}}
        lines = decode(entries, ["00002a"])
        assert lines[0] == "DEBUG The answer is 42!"

    def test_decode_u16_u32(self):
        entries = {"0": {"tag": "Warn", "format": "vals: {=u16} {=u32}"}}
        lines = decode(entries, ["0000ffff01000000"])
        assert lines[0] == "WARN vals: 65535 1"

    def test_decode_bool(self):
        entries = {"0": {"tag": "Error", "format": "flag={=bool}"}}
        lines = decode(entries, ["000001", "000000"])
        assert lines[0] == "ERROR flag=true"
        assert lines[1] == "ERROR flag=false"

    def test_decode_string(self):
        entries = {"0": {"tag": "Info", "format": "Hello {=str}"}}
        lines = decode(entries, ["000005000000576f726c64"])
        assert lines[0] == "INFO Hello World"

    def test_decode_byte_slice(self):
        entries = {"0": {"tag": "Info", "format": "data={=[u8]}"}}
        lines = decode(entries, ["000002000000172a"])
        assert lines[0] == "INFO data=[23, 42]"

    def test_decode_escaped_braces(self):
        entries = {"0": {"tag": "Info", "format": "Foo {{ x: {=u8} }}"}}
        lines = decode(entries, ["00002a"])
        assert lines[0] == "INFO Foo { x: 42 }"

    def test_decode_nested_format(self):
        entries = {
            "0": {"tag": "Info", "format": "x={=?}"},
            "1": {"tag": "Derived", "format": "Foo {{ x: {=u8} }}"},
        }
        lines = decode(entries, ["000001002a"])
        assert lines[0] == "INFO x=Foo { x: 42 }"

    def test_decode_format_slice(self):
        entries = {
            "0": {"tag": "Info", "format": "items={=[?]}"},
            "1": {"tag": "Prim", "format": "{=u8}"},
        }
        frame = "0000" "03000000" "0100" "0a" "0100" "14" "0100" "1e"
        lines = decode(entries, [frame])
        assert lines[0] == "INFO items=[10, 20, 30]"

    def test_decode_argument_reuse(self):
        entries = {"0": {"tag": "Info", "format": "The answer is {0=u8} {0=u8}!"}}
        lines = decode(entries, ["00002a"])
        assert lines[0] == "INFO The answer is 42 42!"

    def test_decode_explicit_indices(self):
        entries = {
            "0": {"tag": "Info", "format": "a={1=u16} b={0=u8} c={1=u16}"}
        }
        lines = decode(entries, ["00002affff"])
        assert lines[0] == "INFO a=65535 b=42 c=65535"


# ===========================================================================
# Group 4: Decode -- display hints
# ===========================================================================

class TestDecodeHints:
    def test_hex_unsigned(self):
        entries = {
            "0": {"tag": "Info", "format": "a={=u8:x} b={=u8:X} c={=u8:#x} d={=u8:#X}"}
        }
        lines = decode(entries, ["00002a2a2a2a"])
        assert lines[0] == "INFO a=2a b=2A c=0x2a d=0x2A"

    def test_binary_display(self):
        entries = {"0": {"tag": "Info", "format": "a={=u8:b} b={=u8:#b}"}}
        lines = decode(entries, ["00002a2a"])
        assert lines[0] == "INFO a=101010 b=0b101010"

    def test_zero_padded(self):
        entries = {"0": {"tag": "Info", "format": "hex={=u8:04x} dec={=u8:03}"}}
        lines = decode(entries, ["00000505"])
        assert lines[0] == "INFO hex=0005 dec=005"

    def test_timestamp_us(self):
        entries = {
            "0": {"tag": "Info", "format": "x={=?}"},
            "1": {"tag": "Derived", "format": "Foo {{ x: {=u8} }}"},
        }
        lines = decode(entries, ["00000201002a"], timestamp="{=u8:us}")
        assert lines[0] == "0.000002 INFO x=Foo { x: 42 }"

    def test_iso8601_seconds(self):
        entries = {"0": {"tag": "Info", "format": "{=u64:iso8601s}"}}
        lines = decode(entries, ["0000a09d7e6000000000"])
        assert lines[0] == "INFO 2021-04-20T09:23:44Z"

    def test_inner_hint_overrides_outer(self):
        """Inner non-Debug hint takes precedence over outer hint."""
        entries = {
            "0": {"tag": "Info", "format": "x={:b}"},
            "1": {"tag": "Derived", "format": "S {{ x: {=u8:x} }}"},
        }
        lines = decode(entries, ["000001002a"])
        assert lines[0] == "INFO x=S { x: 2a }"


# ===========================================================================
# Group 5: Decode -- edge cases (bitfields, signed hex, sequences, ISO)
# ===========================================================================

class TestDecodeEdgeCases:
    def test_bitfield_cross_byte(self):
        """Bitfield range 7..12 across two bytes."""
        entries = {"0": {"tag": "Info", "format": "x: {0=7..12:b}"}}
        lines = decode(entries, ["0000f0e5"])
        assert lines[0] == "INFO x: 1011"

    def test_bitfield_boundary_trailing(self):
        """Bitfield 0..8: max_bit=8 is on byte boundary.
        Correct: (8-1)//8=0, reads 1 byte. Bug: 8//8=1, reads 2 bytes."""
        entries = {"0": {"tag": "Info", "format": "bf={0=0..8} val={1=u8}"}}
        lines = decode(entries, ["0000ff2a00"])
        assert lines[0] == "INFO bf=255 val=42"

    def test_bitfield_boundary_16bit(self):
        """Bitfield 0..16 on byte boundary."""
        entries = {"0": {"tag": "Info", "format": "bf={0=0..16:#x} val={1=u8}"}}
        lines = decode(entries, ["0000abcd4200"])
        assert lines[0] == "INFO bf=0xcdab val=66"

    def test_signed_i8_hex(self):
        """i8 -1 with :x should be 'ff', not 'ffffffff'."""
        entries = {"0": {"tag": "Info", "format": "i8={=i8:x}"}}
        lines = decode(entries, ["0000ff"])
        assert lines[0] == "INFO i8=ff"

    def test_signed_i16_alt_hex(self):
        """i16 -1 with :#x should be '0xffff'."""
        entries = {"0": {"tag": "Info", "format": "i16={=i16:#x}"}}
        lines = decode(entries, ["0000ffff"])
        assert lines[0] == "INFO i16=0xffff"

    def test_signed_i64_hex(self):
        """i64 -1 with :x should produce 16 hex digits."""
        entries = {"0": {"tag": "Info", "format": "i64={=i64:x}"}}
        lines = decode(entries, ["0000ffffffffffffffff"])
        assert lines[0] == "INFO i64=ffffffffffffffff"

    def test_signed_i128_hex(self):
        """i128 -1 with :x should produce 32 hex digits."""
        entries = {"0": {"tag": "Info", "format": "i128={=i128:x}"}}
        lines = decode(entries, ["0000" + "ff" * 16])
        assert lines[0] == "INFO i128=" + "f" * 32

    def test_debug_hint_propagation_binary(self):
        """Outer {:b} with inner {=u8:?} -> format u8 as binary."""
        entries = {
            "0": {"tag": "Info", "format": "x={:b}"},
            "1": {"tag": "Derived", "format": "S {{ x: {=u8:?} }}"},
        }
        lines = decode(entries, ["000001002a"])
        assert lines[0] == "INFO x=S { x: 101010 }"

    def test_debug_hint_propagation_hex(self):
        """Outer {:x} with inner {=u8:?} -> format u8 as hex."""
        entries = {
            "0": {"tag": "Info", "format": "x={:x}"},
            "1": {"tag": "Derived", "format": "V {{ n: {=u8:?} }}"},
        }
        lines = decode(entries, ["00000100ff"])
        assert lines[0] == "INFO x=V { n: ff }"

    def test_format_sequence_decode(self):
        """FormatSequence with u16 LE indices."""
        entries = {
            "0": {"tag": "Info", "format": "{=__internal_FormatSequence}"},
            "1": {"tag": "Derived", "format": "Foo"},
            "2": {"tag": "Derived", "format": "Bar({=u8})"},
        }
        frame = "0000" "0100" "0200" "2a" "0000"
        lines = decode(entries, [frame])
        assert lines[0] == "INFO FooBar(42)"

    def test_format_sequence_three(self):
        entries = {
            "0": {"tag": "Info", "format": "{=__internal_FormatSequence}"},
            "1": {"tag": "Derived", "format": "A"},
            "2": {"tag": "Derived", "format": "B({=u8})"},
            "3": {"tag": "Derived", "format": "C({=u16})"},
        }
        frame = "0000" "0100" "0200" "0a" "0300" "0001" "0000"
        lines = decode(entries, [frame])
        assert lines[0] == "INFO AB(10)C(256)"

    def test_iso8601_ms(self):
        """ISO 8601 millisecond precision."""
        entries = {"0": {"tag": "Info", "format": "{=u64:iso8601ms}"}}
        lines = decode(entries, ["000024bc97ee78010000"])
        assert lines[0] == "INFO 2021-04-20T09:23:44.804Z"


# ===========================================================================
# Group 6: Round-trip tests (encode then decode)
# ===========================================================================

class TestRoundTrip:
    def _roundtrip(self, table_entries, logs, expected_lines, timestamp=None):
        """Encode logs, then decode the resulting frames, verify output."""
        enc_data = {
            "table": {
                "timestamp": {"format": timestamp} if timestamp else None,
                "entries": table_entries,
            },
            "logs": logs,
        }
        hex_frames = _run_codec("encode", enc_data)

        dec_data = {
            "table": {
                "timestamp": {"format": timestamp} if timestamp else None,
                "entries": table_entries,
            },
            "frames": hex_frames,
        }
        dec_lines = _run_codec("decode", dec_data)
        for exp, got in zip(expected_lines, dec_lines):
            assert got == exp, f"Expected: {exp!r}, got: {got!r}"

    def test_roundtrip_simple(self):
        entries = {"0": {"tag": "Info", "format": "Hello, world!"}}
        self._roundtrip(entries, [{"index": 0, "values": []}], ["INFO Hello, world!"])

    def test_roundtrip_u8(self):
        entries = {"0": {"tag": "Debug", "format": "x={=u8}"}}
        self._roundtrip(entries, [{"index": 0, "values": [42]}], ["DEBUG x=42"])

    def test_roundtrip_nested(self):
        entries = {
            "0": {"tag": "Info", "format": "x={=?}"},
            "1": {"tag": "Derived", "format": "Foo {{ x: {=u8} }}"},
        }
        self._roundtrip(
            entries,
            [{"index": 0, "values": [{"format_ref": 1, "values": [42]}]}],
            ["INFO x=Foo { x: 42 }"],
        )

    def test_roundtrip_sequence(self):
        entries = {
            "0": {"tag": "Info", "format": "{=__internal_FormatSequence}"},
            "1": {"tag": "Derived", "format": "A"},
            "2": {"tag": "Derived", "format": "B({=u8})"},
        }
        self._roundtrip(
            entries,
            [{"index": 0, "values": [[
                {"format_ref": 1, "values": []},
                {"format_ref": 2, "values": [42]},
            ]]}],
            ["INFO AB(42)"],
        )

    def test_roundtrip_timestamp(self):
        entries = {
            "0": {"tag": "Info", "format": "x={=u8}"},
        }
        self._roundtrip(
            entries,
            [{"index": 0, "values": [42], "timestamp_values": [2]}],
            ["0.000002 INFO x=42"],
            timestamp="{=u8:us}",
        )

    def test_roundtrip_signed_hex(self):
        entries = {"0": {"tag": "Info", "format": "v={=i8:x}"}}
        self._roundtrip(
            entries,
            [{"index": 0, "values": [-1]}],
            ["INFO v=ff"],
        )

    def test_roundtrip_multiple_frames(self):
        entries = {
            "0": {"tag": "Info", "format": "Hello"},
            "1": {"tag": "Debug", "format": "x={=u8}"},
            "2": {"tag": "Error", "format": "flag={=bool}"},
        }
        self._roundtrip(
            entries,
            [
                {"index": 0, "values": []},
                {"index": 1, "values": [42]},
                {"index": 2, "values": [True]},
            ],
            ["INFO Hello", "DEBUG x=42", "ERROR flag=true"],
        )
