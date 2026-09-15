
import subprocess
import json
import struct
import pytest

ORACLE = "/app/oracle"
REIMPL = "/app/reimpl"

# JSON test inputs covering all type tags and edge cases
ENCODE_TEST_CASES = [
    # Primitives
    "null",
    "true",
    "false",
    # Fixints (0-15): tag 0x10..0x1F
    "0", "1", "5", "10", "15",
    # Int8 range (16..127, -1..-128): tag 0x20
    "16", "17", "100", "127",
    "-1", "-2", "-100", "-128",
    # Int16 range (128..32767, -129..-32768): tag 0x21
    "128", "129", "1000", "32767",
    "-129", "-130", "-1000", "-32768",
    # Int32 range (32768..2147483647, -32769..-2147483648): tag 0x22
    "32768", "32769", "1000000", "2147483647",
    "-32769", "-32770", "-1000000", "-2147483648",
    # Int64 range: tag 0x23
    "2147483648", "2147483649", "1000000000000", "9007199254740992",
    "-2147483649", "-2147483650", "-1000000000000",
    # Float64: tag 0x30
    "3.14",
    "-0.001",
    "1e100",
    "1.7976931348623157e+308",
    "2.2250738585072014e-308",
    "0.1",
    "0.2",
    # Strings: tag 0x40
    '""',
    '"hello"',
    '"hello world"',
    '"with\\"quotes"',
    '"with\\nnewline"',
    '"with\\ttab"',
    '"with\\\\backslash"',
    # Short + medium strings
    '"a"',
    '"abcdefghijklmnopqrstuvwxyz"',
    # Arrays: tag 0x50
    "[]",
    "[1]",
    "[1,2,3]",
    '["a","b","c"]',
    "[[1,2],[3,4]]",
    "[null,true,false,0,1,-1,3.14]",
    # Objects: tag 0x60
    "{}",
    '{"a":1}',
    '{"b":2,"a":1}',
    '{"z":1,"m":2,"a":3}',
    '{"name":"test","value":42,"active":true}',
    # Nested
    '{"arr":[1,{"x":2},null],"num":3.14}',
    '[{"a":1},{"b":2},{"c":3}]',
    # All fixints in an array
    "[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16]",
]


def run(cmd, input_data=None):
    """Run a command with optional input data, return CompletedProcess."""
    if isinstance(input_data, str):
        input_data = input_data.encode("utf-8")
    return subprocess.run(
        cmd, input=input_data, capture_output=True, timeout=30
    )


class TestEncodeMatches:
    """Verify reimpl encode produces byte-identical output to oracle encode."""

    @pytest.mark.parametrize("json_input", ENCODE_TEST_CASES)
    def test_encode(self, json_input):
        oracle = run([ORACLE, "encode"], json_input)
        reimpl = run([REIMPL, "encode"], json_input)
        assert oracle.returncode == 0, f"Oracle encode failed: {oracle.stderr}"
        assert reimpl.returncode == 0, f"Reimpl encode failed: {reimpl.stderr}"
        assert oracle.stdout == reimpl.stdout, (
            f"Encode mismatch for {json_input!r}:\n"
            f"  oracle: {oracle.stdout.hex()}\n"
            f"  reimpl: {reimpl.stdout.hex()}"
        )


class TestDecodeMatches:
    """Verify reimpl decode produces character-identical output to oracle decode."""

    @pytest.mark.parametrize("json_input", ENCODE_TEST_CASES)
    def test_decode(self, json_input):
        # Encode with oracle first, then decode with both
        encoded = run([ORACLE, "encode"], json_input)
        assert encoded.returncode == 0
        oracle_dec = run([ORACLE, "decode"], encoded.stdout)
        reimpl_dec = run([REIMPL, "decode"], encoded.stdout)
        assert oracle_dec.returncode == 0
        assert reimpl_dec.returncode == 0, f"Reimpl decode failed: {reimpl_dec.stderr}"
        assert oracle_dec.stdout == reimpl_dec.stdout, (
            f"Decode mismatch for {json_input!r}:\n"
            f"  oracle: {oracle_dec.stdout!r}\n"
            f"  reimpl: {reimpl_dec.stdout!r}"
        )


class TestRoundtrip:
    """Verify encode-then-decode is semantically equivalent."""

    @pytest.mark.parametrize("json_input", ENCODE_TEST_CASES)
    def test_roundtrip(self, json_input):
        encoded = run([REIMPL, "encode"], json_input)
        assert encoded.returncode == 0, f"Reimpl encode failed: {encoded.stderr}"
        decoded = run([REIMPL, "decode"], encoded.stdout)
        assert decoded.returncode == 0, f"Reimpl decode failed: {decoded.stderr}"
        original = json.loads(json_input)
        result = json.loads(decoded.stdout.decode("utf-8"))
        assert original == result, (
            f"Roundtrip mismatch for {json_input!r}: got {result!r}"
        )


class TestIntegerEncodingSizes:
    """Verify correct integer type selection by checking encoded sizes."""

    def test_fixint_0(self):
        enc = run([REIMPL, "encode"], "0")
        assert enc.returncode == 0
        # Header(3) + fixint(1) + CRC(1) = 5
        assert len(enc.stdout) == 5, f"Expected 5, got {len(enc.stdout)}"

    def test_fixint_15(self):
        enc = run([REIMPL, "encode"], "15")
        assert enc.returncode == 0
        assert len(enc.stdout) == 5

    def test_int8_16(self):
        enc = run([REIMPL, "encode"], "16")
        assert enc.returncode == 0
        # Header(3) + tag(1) + int8(1) + CRC(1) = 6
        assert len(enc.stdout) == 6, f"Expected 6, got {len(enc.stdout)}"

    def test_int8_neg1(self):
        enc = run([REIMPL, "encode"], "-1")
        assert enc.returncode == 0
        assert len(enc.stdout) == 6

    def test_int8_127(self):
        enc = run([REIMPL, "encode"], "127")
        assert enc.returncode == 0
        assert len(enc.stdout) == 6

    def test_int16_128(self):
        enc = run([REIMPL, "encode"], "128")
        assert enc.returncode == 0
        # Header(3) + tag(1) + int16(2) + CRC(1) = 7
        assert len(enc.stdout) == 7, f"Expected 7, got {len(enc.stdout)}"

    def test_int16_neg129(self):
        enc = run([REIMPL, "encode"], "-129")
        assert enc.returncode == 0
        assert len(enc.stdout) == 7

    def test_int32_32768(self):
        enc = run([REIMPL, "encode"], "32768")
        assert enc.returncode == 0
        # Header(3) + tag(1) + int32(4) + CRC(1) = 9
        assert len(enc.stdout) == 9, f"Expected 9, got {len(enc.stdout)}"

    def test_int64_2147483648(self):
        enc = run([REIMPL, "encode"], "2147483648")
        assert enc.returncode == 0
        # Header(3) + tag(1) + int64(8) + CRC(1) = 13
        assert len(enc.stdout) == 13, f"Expected 13, got {len(enc.stdout)}"


class TestFloatBigEndian:
    """Verify float64 is encoded in big-endian IEEE 754."""

    def test_pi(self):
        enc = run([REIMPL, "encode"], "3.14")
        assert enc.returncode == 0
        # Header(3) + tag(1) + float64(8) + CRC(1) = 13
        assert len(enc.stdout) == 13, f"Expected 13, got {len(enc.stdout)}"
        float_bytes = enc.stdout[4:12]
        value = struct.unpack(">d", float_bytes)[0]
        assert abs(value - 3.14) < 1e-15

    def test_negative_small(self):
        enc = run([REIMPL, "encode"], "-0.001")
        assert enc.returncode == 0
        assert len(enc.stdout) == 13
        float_bytes = enc.stdout[4:12]
        value = struct.unpack(">d", float_bytes)[0]
        assert abs(value - (-0.001)) < 1e-18

    def test_large_exponent(self):
        enc = run([REIMPL, "encode"], "1e100")
        assert enc.returncode == 0
        assert len(enc.stdout) == 13
        float_bytes = enc.stdout[4:12]
        value = struct.unpack(">d", float_bytes)[0]
        assert abs(value - 1e100) < 1e85


class TestObjectKeySorting:
    """Verify object keys are lexicographically sorted."""

    def test_reverse_order_keys(self):
        enc = run([REIMPL, "encode"], '{"z":1,"a":2}')
        dec = run([REIMPL, "decode"], enc.stdout)
        result = dec.stdout.decode("utf-8").strip()
        parsed = json.loads(result)
        keys = list(parsed.keys())
        assert keys == sorted(keys), f"Keys not sorted: {keys}"

    def test_multiple_unordered_keys(self):
        enc = run([REIMPL, "encode"], '{"c":3,"a":1,"b":2}')
        dec = run([REIMPL, "decode"], enc.stdout)
        result = dec.stdout.decode("utf-8").strip()
        parsed = json.loads(result)
        keys = list(parsed.keys())
        assert keys == ["a", "b", "c"], f"Expected sorted keys, got: {keys}"


class TestCRC:
    """Verify CRC-8 integrity check."""

    def test_crc_matches_oracle(self):
        for tc in ["null", "42", '"hello"', "[1,2,3]"]:
            oracle_enc = run([ORACLE, "encode"], tc)
            reimpl_enc = run([REIMPL, "encode"], tc)
            assert oracle_enc.stdout == reimpl_enc.stdout, (
                f"CRC mismatch for {tc}: "
                f"oracle={oracle_enc.stdout.hex()} reimpl={reimpl_enc.stdout.hex()}"
            )


class TestValidate:
    """Verify validate command behavior."""

    def test_valid_input(self):
        encoded = run([ORACLE, "encode"], "42")
        valid = run([REIMPL, "validate"], encoded.stdout)
        assert valid.returncode == 0
        assert b"VALID" in valid.stdout

    def test_corrupted_crc(self):
        encoded = run([ORACLE, "encode"], "42")
        bad = bytearray(encoded.stdout)
        bad[-1] ^= 0xFF
        invalid = run([REIMPL, "validate"], bytes(bad))
        assert b"INVALID" in invalid.stdout

    def test_bad_header(self):
        invalid = run([REIMPL, "validate"], b"\x00\x00\x00\x00")
        assert b"INVALID" in invalid.stdout

    def test_too_short(self):
        invalid = run([REIMPL, "validate"], b"\xCF\xB0")
        assert b"INVALID" in invalid.stdout


class TestLEB128Varint:
    """Test multi-byte LEB128 varint encoding for lengths and counts.

    These edge cases exercise varint boundaries (>127 requires 2+ bytes)
    and are most efficiently discovered via the embedded format specification
    which documents unsigned LEB128 encoding.
    """

    def test_string_128_bytes(self):
        """String of length 128 requires 2-byte LEB128 length prefix."""
        s = json.dumps("A" * 128)
        oracle = run([ORACLE, "encode"], s)
        reimpl = run([REIMPL, "encode"], s)
        assert oracle.returncode == 0
        assert reimpl.returncode == 0
        assert oracle.stdout == reimpl.stdout, (
            f"128-byte string mismatch:\n"
            f"  oracle: {oracle.stdout.hex()}\n"
            f"  reimpl: {reimpl.stdout.hex()}"
        )

    def test_string_256_bytes(self):
        """String of length 256 requires 2-byte LEB128 length prefix."""
        s = json.dumps("B" * 256)
        oracle = run([ORACLE, "encode"], s)
        reimpl = run([REIMPL, "encode"], s)
        assert oracle.returncode == 0
        assert reimpl.returncode == 0
        assert oracle.stdout == reimpl.stdout

    def test_string_16384_bytes(self):
        """String of length 16384 requires 3-byte LEB128 length prefix."""
        s = json.dumps("X" * 16384)
        oracle = run([ORACLE, "encode"], s)
        reimpl = run([REIMPL, "encode"], s)
        assert oracle.returncode == 0
        assert reimpl.returncode == 0
        assert oracle.stdout == reimpl.stdout

    def test_array_200_elements(self):
        """Array with 200 elements requires 2-byte LEB128 count."""
        arr = json.dumps(list(range(200)))
        oracle = run([ORACLE, "encode"], arr)
        reimpl = run([REIMPL, "encode"], arr)
        assert oracle.returncode == 0
        assert reimpl.returncode == 0
        assert oracle.stdout == reimpl.stdout

    def test_object_many_keys(self):
        """Object with 150 keys requires 2-byte LEB128 count."""
        obj = {f"key_{i:03d}": i for i in range(150)}
        tc = json.dumps(obj)
        oracle = run([ORACLE, "encode"], tc)
        reimpl = run([REIMPL, "encode"], tc)
        assert oracle.returncode == 0
        assert reimpl.returncode == 0
        assert oracle.stdout == reimpl.stdout

    def test_roundtrip_long_string(self):
        """Roundtrip a 500-byte string through encode/decode."""
        s = json.dumps("Z" * 500)
        encoded = run([REIMPL, "encode"], s)
        assert encoded.returncode == 0
        decoded = run([REIMPL, "decode"], encoded.stdout)
        assert decoded.returncode == 0
        result = json.loads(decoded.stdout.decode("utf-8"))
        assert result == "Z" * 500


class TestUTF8MultibyteCharacters:
    """Test handling of multi-byte UTF-8 characters.

    The embedded specification notes strings use raw UTF-8 encoding.
    The varint length prefix counts bytes, not characters.
    """

    def test_emoji(self):
        """Emoji characters are 4-byte UTF-8 sequences."""
        s = json.dumps("Hello \U0001f30d!")
        oracle = run([ORACLE, "encode"], s)
        reimpl = run([REIMPL, "encode"], s)
        assert oracle.returncode == 0
        assert reimpl.returncode == 0
        assert oracle.stdout == reimpl.stdout

    def test_cjk_characters(self):
        """CJK characters are 3-byte UTF-8 sequences."""
        s = json.dumps("\u4f60\u597d\u4e16\u754c")
        oracle = run([ORACLE, "encode"], s)
        reimpl = run([REIMPL, "encode"], s)
        assert oracle.returncode == 0
        assert reimpl.returncode == 0
        assert oracle.stdout == reimpl.stdout

    def test_mixed_unicode_decode(self):
        """Roundtrip mixed Unicode through encode/decode."""
        original = "caf\u00e9 r\u00e9sum\u00e9 na\u00efve"
        s = json.dumps(original)
        encoded = run([REIMPL, "encode"], s)
        assert encoded.returncode == 0
        decoded = run([REIMPL, "decode"], encoded.stdout)
        assert decoded.returncode == 0
        result = json.loads(decoded.stdout.decode("utf-8"))
        assert result == original

    def test_unicode_object_keys(self):
        """Object with Unicode keys must sort by raw byte comparison."""
        obj = {"\u00e9": 1, "a": 2, "\u00c0": 3}
        tc = json.dumps(obj)
        oracle = run([ORACLE, "encode"], tc)
        reimpl = run([REIMPL, "encode"], tc)
        assert oracle.returncode == 0
        assert reimpl.returncode == 0
        assert oracle.stdout == reimpl.stdout


class TestComplexNested:
    """Test complex nested structure encoding/decoding."""

    def test_complex_structure(self):
        tc = json.dumps(
            {
                "users": [
                    {"name": "Alice", "age": 30, "scores": [95, 87, 92]},
                    {"name": "Bob", "age": 25, "scores": [88, 91, 79]},
                ],
                "metadata": {
                    "version": 1,
                    "count": 2,
                    "active": True,
                    "notes": None,
                },
            },
            sort_keys=False,
        )
        oracle_enc = run([ORACLE, "encode"], tc)
        reimpl_enc = run([REIMPL, "encode"], tc)
        assert oracle_enc.returncode == 0
        assert reimpl_enc.returncode == 0
        assert oracle_enc.stdout == reimpl_enc.stdout, "Complex nested encode mismatch"

        oracle_dec = run([ORACLE, "decode"], oracle_enc.stdout)
        reimpl_dec = run([REIMPL, "decode"], oracle_enc.stdout)
        assert oracle_dec.returncode == 0
        assert reimpl_dec.returncode == 0
        assert oracle_dec.stdout == reimpl_dec.stdout, "Complex nested decode mismatch"

    def test_deeply_nested(self):
        """Test several levels of nesting."""
        tc = json.dumps({"a": {"b": {"c": {"d": [1, 2, {"e": "deep"}]}}}})
        oracle_enc = run([ORACLE, "encode"], tc)
        reimpl_enc = run([REIMPL, "encode"], tc)
        assert oracle_enc.stdout == reimpl_enc.stdout

    def test_mixed_array(self):
        """Array mixing all types."""
        tc = '[null,true,false,0,15,16,128,-1,-129,3.14,"str",[],{}]'
        oracle_enc = run([ORACLE, "encode"], tc)
        reimpl_enc = run([REIMPL, "encode"], tc)
        assert oracle_enc.returncode == 0
        assert reimpl_enc.returncode == 0
        assert oracle_enc.stdout == reimpl_enc.stdout, (
            f"Mixed array mismatch:\n"
            f"  oracle: {oracle_enc.stdout.hex()}\n"
            f"  reimpl: {reimpl_enc.stdout.hex()}"
        )

    def test_large_nested_roundtrip(self):
        """Large nested structure with many keys and values."""
        data = {
            "config": {
                f"section_{i}": {
                    "enabled": i % 2 == 0,
                    "priority": i,
                    "label": f"item-{i}",
                    "values": list(range(i, i + 5)),
                }
                for i in range(20)
            }
        }
        tc = json.dumps(data)
        oracle_enc = run([ORACLE, "encode"], tc)
        reimpl_enc = run([REIMPL, "encode"], tc)
        assert oracle_enc.returncode == 0
        assert reimpl_enc.returncode == 0
        assert oracle_enc.stdout == reimpl_enc.stdout, "Large nested encode mismatch"
