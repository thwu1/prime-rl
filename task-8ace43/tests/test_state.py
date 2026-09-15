"""
Tests for CStore binary codec reimplementation.
Compares agent's /app/solution.py against reference /app/cstore.

"""
import subprocess
import os
import pytest
from contextlib import contextmanager

REF = "/app/cstore"
IMPL = "/app/solution.py"


@contextmanager
def with_salt(salt_value):
    """Set CSTORE_SALT env var for the duration of the block."""
    old = os.environ.get("CSTORE_SALT")
    os.environ["CSTORE_SALT"] = salt_value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("CSTORE_SALT", None)
        else:
            os.environ["CSTORE_SALT"] = old


def ref_run(cmd, data):
    r = subprocess.run([REF, cmd], input=data, capture_output=True)
    return r.stdout, r.stderr, r.returncode


def impl_run(cmd, data):
    r = subprocess.run(["python3", IMPL, cmd], input=data, capture_output=True)
    return r.stdout, r.stderr, r.returncode


def assert_encode_match(json_str):
    """Byte-identical encode output."""
    data = json_str.encode("utf-8")
    ro, _, rc = ref_run("encode", data)
    io, ie, ic = impl_run("encode", data)
    assert ic == 0, f"impl encode failed for {json_str!r}: {ie.decode(errors='replace')}"
    assert ro == io, (
        f"Encode mismatch for {json_str!r}:\n"
        f"  ref ({len(ro)}b): {ro[:80].hex()}\n"
        f"  impl({len(io)}b): {io[:80].hex()}"
    )


def assert_decode_match(json_str):
    """Character-identical decode output from reference-encoded data."""
    data = json_str.encode("utf-8")
    encoded, _, _ = ref_run("encode", data)
    ro, _, rc = ref_run("decode", encoded)
    io, ie, ic = impl_run("decode", encoded)
    assert ic == 0, f"impl decode failed: {ie.decode(errors='replace')}"
    assert ro == io, (
        f"Decode mismatch for {json_str!r}:\n"
        f"  ref : {ro!r}\n"
        f"  impl: {io!r}"
    )


def assert_info_match(json_str):
    """Character-identical info output."""
    data = json_str.encode("utf-8")
    encoded, _, _ = ref_run("encode", data)
    ro, _, _ = ref_run("info", encoded)
    io, ie, ic = impl_run("info", encoded)
    assert ic == 0, f"impl info failed: {ie.decode(errors='replace')}"
    assert ro == io, (
        f"Info mismatch for {json_str!r}:\n"
        f"  ref : {ro.decode()!r}\n"
        f"  impl: {io.decode()!r}"
    )


def assert_roundtrip(json_str):
    """Encode and decode both match reference."""
    assert_encode_match(json_str)
    assert_decode_match(json_str)


# ==================== Encode: Basic Types ====================


class TestEncodeBasicTypes:
    def test_null(self):
        assert_encode_match("null")

    def test_true(self):
        assert_encode_match("true")

    def test_false(self):
        assert_encode_match("false")

    def test_integer_zero(self):
        assert_encode_match("0")

    def test_integer_positive(self):
        assert_encode_match("42")

    def test_integer_negative(self):
        assert_encode_match("-7")

    def test_integer_one(self):
        assert_encode_match("1")

    def test_integer_neg_one(self):
        assert_encode_match("-1")

    def test_integer_large(self):
        assert_encode_match("123456789")

    def test_integer_large_negative(self):
        assert_encode_match("-123456789")

    def test_float_simple(self):
        assert_encode_match("3.14")

    def test_float_zero(self):
        assert_encode_match("0.0")

    def test_float_negative(self):
        assert_encode_match("-2.718")

    def test_float_scientific(self):
        assert_encode_match("1.5e10")

    def test_float_scientific_negative_exp(self):
        assert_encode_match("6.022e-5")

    def test_string_empty(self):
        assert_encode_match('""')

    def test_string_simple(self):
        assert_encode_match('"hello world"')

    def test_string_escapes(self):
        assert_encode_match(r'"line1\nline2\ttab\"quote\\slash"')

    def test_string_unicode(self):
        assert_encode_match('"caf\\u00e9"')


# ==================== Encode: Containers ====================


class TestEncodeContainers:
    def test_array_empty(self):
        assert_encode_match("[]")

    def test_array_simple(self):
        assert_encode_match("[1, 2, 3]")

    def test_array_mixed(self):
        assert_encode_match('[1, "two", true, null, 3.14]')

    def test_array_nested(self):
        assert_encode_match("[[1, 2], [3, 4]]")

    def test_object_empty(self):
        assert_encode_match("{}")

    def test_object_simple(self):
        assert_encode_match('{"name": "alice", "age": 30}')

    def test_object_key_sorting(self):
        """Keys must be sorted by raw UTF-8 bytes in the encoding."""
        assert_encode_match('{"z": 1, "a": 2, "m": 3}')

    def test_object_duplicate_keys(self):
        """Last occurrence of duplicate key wins."""
        assert_encode_match('{"a": 1, "b": 2, "a": 99}')

    def test_nested_complex(self):
        assert_encode_match(
            '{"users": [{"name": "alice", "scores": [95, 87]}, '
            '{"name": "bob", "scores": [72, 91]}]}'
        )


# ==================== Encode: Edge Cases ====================


class TestEncodeEdgeCases:
    def test_negative_zero(self):
        """Negative zero should be normalized to positive zero in encoding."""
        assert_encode_match("-0.0")

    def test_integer_vs_float_distinction(self):
        """3 (integer) and 3.0 (float) should produce different encodings."""
        data_int = b"3"
        data_flt = b"3.0"
        ri, _, _ = ref_run("encode", data_int)
        rf, _, _ = ref_run("encode", data_flt)
        ii, _, _ = impl_run("encode", data_int)
        iflt, _, _ = impl_run("encode", data_flt)
        assert ri == ii, "Integer 3 encoding mismatch"
        assert rf == iflt, "Float 3.0 encoding mismatch"
        assert ri != rf, "Integer 3 and float 3.0 should differ"

    def test_integer_max(self):
        assert_encode_match("9223372036854775807")

    def test_integer_min(self):
        assert_encode_match("-9223372036854775808")

    def test_integer_overflow_to_float(self):
        """Integer too large for int64 should be encoded as float."""
        assert_encode_match("9223372036854775808")

    def test_deeply_nested(self):
        assert_encode_match("[[[[[1]]]]]")

    def test_large_array(self):
        import json
        arr = list(range(200))
        assert_encode_match(json.dumps(arr))

    def test_whitespace_handling(self):
        """JSON with various whitespace should encode identically."""
        compact = '{"a":1,"b":2}'
        spaced = ' { "a" : 1 , "b" : 2 } '
        rc, _, _ = ref_run("encode", compact.encode())
        rs, _, _ = ref_run("encode", spaced.encode())
        ic, _, _ = impl_run("encode", compact.encode())
        iss, _, _ = impl_run("encode", spaced.encode())
        assert rc == rs, "Ref should produce same encoding regardless of whitespace"
        assert ic == iss, "Impl should produce same encoding regardless of whitespace"
        assert rc == ic, "Compact encoding mismatch"

    def test_empty_key(self):
        assert_encode_match('{"": 42}')

    def test_varint_boundary_127(self):
        assert_encode_match("127")

    def test_varint_boundary_128(self):
        assert_encode_match("128")

    def test_varint_large(self):
        assert_encode_match("100000")

    def test_string_control_chars(self):
        """Control characters should be properly handled."""
        assert_encode_match('"hello\\u0000world"')

    def test_object_many_keys(self):
        """Object with many keys to test sorting."""
        import json
        obj = {chr(i): i for i in range(ord("a"), ord("z") + 1)}
        assert_encode_match(json.dumps(obj))


# ==================== Decode ====================


class TestDecode:
    def test_decode_null(self):
        assert_decode_match("null")

    def test_decode_bool(self):
        assert_decode_match("true")
        assert_decode_match("false")

    def test_decode_integer(self):
        assert_decode_match("42")

    def test_decode_integer_negative(self):
        assert_decode_match("-100")

    def test_decode_float(self):
        assert_decode_match("3.14")

    def test_decode_float_whole_number(self):
        """Float that is a whole number should have .0 suffix."""
        assert_decode_match("3.0")

    def test_decode_string(self):
        assert_decode_match('"hello world"')

    def test_decode_string_with_escapes(self):
        assert_decode_match(r'"tab\there\nnewline"')

    def test_decode_array(self):
        assert_decode_match("[1, 2, 3]")

    def test_decode_object(self):
        assert_decode_match('{"b": 2, "a": 1}')

    def test_decode_complex(self):
        assert_decode_match(
            '{"config": {"debug": false, "version": "1.2.3"}, '
            '"data": [1, 2.5, null, true]}'
        )

    def test_decode_empty_containers(self):
        assert_decode_match("[]")
        assert_decode_match("{}")

    def test_decode_negative_zero(self):
        """Decoded -0.0 should normalize to 0.0."""
        assert_decode_match("-0.0")

    def test_decode_integer_vs_float(self):
        """Integers decode without .0, floats with .0 if whole."""
        # Encode 3 (int) and decode
        enc_int, _, _ = ref_run("encode", b"3")
        dec_int, _, _ = ref_run("decode", enc_int)
        impl_dec_int, _, _ = impl_run("decode", enc_int)
        assert impl_dec_int == dec_int

        # Encode 3.0 (float) and decode
        enc_flt, _, _ = ref_run("encode", b"3.0")
        dec_flt, _, _ = ref_run("decode", enc_flt)
        impl_dec_flt, _, _ = impl_run("decode", enc_flt)
        assert impl_dec_flt == dec_flt

        # They should differ: "3\n" vs "3.0\n"
        assert dec_int != dec_flt


# ==================== Info ====================


class TestInfo:
    def test_info_null(self):
        assert_info_match("null")

    def test_info_integer(self):
        assert_info_match("42")

    def test_info_array(self):
        assert_info_match("[1, 2, 3]")

    def test_info_object(self):
        assert_info_match('{"a": 1, "b": [2, 3]}')

    def test_info_complex(self):
        assert_info_match(
            '{"x": [{"y": [1, 2]}, {"z": 3}], "w": "hello"}'
        )

    def test_info_deeply_nested(self):
        assert_info_match("[[[[[42]]]]]")

    def test_info_empty_containers(self):
        assert_info_match("[]")
        assert_info_match("{}")


# ==================== Roundtrip ====================


class TestRoundtrip:
    def test_roundtrip_complex_object(self):
        assert_roundtrip(
            '{"alpha": [1, 2.0, "three"], "beta": {"nested": true}, "gamma": null}'
        )

    def test_roundtrip_deep_nesting(self):
        assert_roundtrip('{"a": {"b": {"c": {"d": [1, 2, 3]}}}}')

    def test_roundtrip_special_strings(self):
        assert_roundtrip(r'{"key\nwith\nnewlines": "value\twith\ttabs"}')

    def test_roundtrip_many_types(self):
        import json
        data = {
            "int": 42,
            "neg": -100,
            "flt": 2.718,
            "str": "hello",
            "bool_t": True,
            "bool_f": False,
            "nil": None,
            "arr": [1, "two", 3.0],
            "obj": {"inner": "value"},
        }
        assert_roundtrip(json.dumps(data))

    def test_encode_then_decode_produces_sorted_keys(self):
        """Encoding unsorted keys then decoding should yield sorted output."""
        enc, _, _ = ref_run("encode", b'{"z": 1, "a": 2, "m": 3}')
        ref_dec, _, _ = ref_run("decode", enc)
        impl_dec, _, _ = impl_run("decode", enc)
        assert impl_dec == ref_dec
        # Verify keys are sorted in output
        decoded_text = ref_dec.decode("utf-8")
        a_pos = decoded_text.index('"a"')
        m_pos = decoded_text.index('"m"')
        z_pos = decoded_text.index('"z"')
        assert a_pos < m_pos < z_pos, "Keys should be sorted"


# ==================== Salted CRC (environment-dependent) ====================


class TestSaltedCRC:
    """Tests for the CSTORE_SALT environment variable behavior.
    The binary uses CSTORE_SALT to modify the CRC32 seed, which changes
    the checksum trailer. This must be discovered via binary analysis
    tools (strings, ltrace, strace) and correctly reimplemented."""

    def test_salted_encode_basic(self):
        """Encode with CSTORE_SALT set must match reference."""
        with with_salt("alpha"):
            assert_encode_match("42")

    def test_salted_encode_string(self):
        """Encode string data with salt."""
        with with_salt("bravo"):
            assert_encode_match('"hello world"')

    def test_salted_encode_complex(self):
        """Encode complex JSON with salt."""
        with with_salt("charlie"):
            assert_encode_match(
                '{"users": [{"name": "alice", "age": 30}, '
                '{"name": "bob", "age": 25}]}'
            )

    def test_salted_vs_unsalted_differs(self):
        """Salted and unsalted encodings must differ."""
        data = b'"test data"'
        unsalted_out, _, _ = ref_run("encode", data)
        with with_salt("secret"):
            salted_out, _, _ = ref_run("encode", data)
        assert unsalted_out != salted_out, "Salted encoding should differ from unsalted"

    def test_salt_only_affects_crc(self):
        """Salt modifies only the CRC trailer, not the body."""
        data = b'{"key": "value"}'
        unsalted_out, _, _ = ref_run("encode", data)
        with with_salt("delta"):
            salted_out, _, _ = ref_run("encode", data)
        # Body (everything except last 4 bytes = CRC) must be identical
        assert unsalted_out[:-4] == salted_out[:-4], "Body should be identical"
        assert unsalted_out[-4:] != salted_out[-4:], "CRC trailer should differ"

    def test_salted_decode_match(self):
        """Decode data encoded with a salt, using the same salt."""
        with with_salt("echo"):
            assert_decode_match("42")
            assert_decode_match('[1, "two", 3.0]')

    def test_salted_info_match(self):
        """Info output with salt must match reference."""
        with with_salt("foxtrot"):
            assert_info_match('{"a": 1, "b": [2, 3]}')

    def test_salted_roundtrip(self):
        """Full roundtrip with salt must work."""
        with with_salt("golf"):
            assert_roundtrip('{"x": [1, 2.0, "three"], "y": null}')

    def test_wrong_salt_decode_fails(self):
        """Decoding with a different salt should fail CRC check."""
        data = b'"test"'
        with with_salt("correct_salt"):
            encoded, _, _ = ref_run("encode", data)
        # Decode with wrong salt — both ref and impl should reject
        with with_salt("wrong_salt"):
            _, _, ref_rc = ref_run("decode", encoded)
            _, _, impl_rc = impl_run("decode", encoded)
            assert ref_rc != 0, "Ref should reject wrong salt"
            assert impl_rc != 0, "Impl should reject wrong salt"

    def test_different_salts_differ(self):
        """Different salt values produce different CRCs."""
        data = b"42"
        with with_salt("aaa"):
            out_a, _, _ = ref_run("encode", data)
            impl_a, _, _ = impl_run("encode", data)
        with with_salt("bbb"):
            out_b, _, _ = ref_run("encode", data)
            impl_b, _, _ = impl_run("encode", data)
        assert out_a != out_b, "Different salts should produce different output"
        assert impl_a == out_a, "Impl should match ref with salt 'aaa'"
        assert impl_b == out_b, "Impl should match ref with salt 'bbb'"

    def test_long_salt_wraps(self):
        """Salt longer than 4 bytes exercises the modular byte positioning."""
        with with_salt("longersaltvalue"):
            assert_encode_match('{"nested": {"data": [1, 2, 3]}}')
