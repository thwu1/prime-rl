#!/usr/bin/env python3
"""Fix the four bugs in compact/codec.py, write property-based tests,
and produce a structured bug taxonomy report.

Bug 1: _zigzag_encode uses (n << 1) ^ (n >> 63), which silently
        produces wrong results for integers outside the 64-bit range
        because Python integers are arbitrary-precision.

Bug 2: _encode_float treats -0.0 the same as 0.0 (since -0.0 == 0.0
        is True in Python) and emits the TAG_FLOAT_ZERO shorthand,
        losing the sign bit.

Bug 3: In the TAG_DICT decoder, position is advanced by len(key)
        (character count) instead of key_byte_len (UTF-8 byte count),
        causing misalignment for non-ASCII keys.

Bug 4: The tuple encoder writes len(inner_buf) (serialized byte
        length) as the count prefix, but the decoder interprets it
        as the number of elements.
"""

import json
import os

# ---- read the original source ----
codec_path = '/app/compact/codec.py'
with open(codec_path) as f:
    src = f.read()

# ---- Fix 1: zigzag encoding for arbitrary-precision integers ----
src = src.replace(
    '    return (n << 1) ^ (n >> 63)',
    '    if n >= 0:\n        return n << 1\n    return (-n << 1) - 1',
)

# ---- Fix 2: preserve negative zero ----
src = src.replace(
    '    elif value == 0.0:\n        buf.append(TAG_FLOAT_ZERO)',
    '    elif value == 0.0 and math.copysign(1.0, value) > 0:\n        buf.append(TAG_FLOAT_ZERO)',
)

# ---- Fix 3: dict key position tracking (bytes, not chars) ----
src = src.replace(
    '            pos += len(key)\n            val, pos = _decode_value(data, pos)',
    '            pos += key_byte_len\n            val, pos = _decode_value(data, pos)',
)

# ---- Fix 4: tuple element count, not byte count ----
src = src.replace(
    """\
    elif isinstance(value, tuple):
        buf.append(TAG_TUPLE)
        # Serialize elements into a temporary buffer so we can prefix
        # the total serialized size for efficient skipping.
        inner_buf = bytearray()
        for item in value:
            _encode_value(inner_buf, item)
        buf.extend(encode_varint(len(inner_buf)))
        buf.extend(inner_buf)""",
    """\
    elif isinstance(value, tuple):
        buf.append(TAG_TUPLE)
        buf.extend(encode_varint(len(value)))
        for item in value:
            _encode_value(buf, item)""",
)

with open(codec_path, 'w') as f:
    f.write(src)

print('[solve] Fixed 4 bugs in compact/codec.py')

# ---- Write Hypothesis property-based tests ----
pbt_code = '''\
"""Property-based tests for the compact codec, written with Hypothesis.

Tests three distinct property categories:
  1. Roundtrip identity — encode(decode(v)) == v for all supported types
  2. Type and sign preservation — decoded values have the exact same
     Python type and IEEE 754 sign as the originals
  3. Encoding determinism — the same value always encodes to the same bytes
"""

import math
import struct
import sys

sys.path.insert(0, '/app')

from hypothesis import given, settings, strategies as st, assume
from compact import encode, decode


# -- custom composite strategy for the codec's recursive type system --
compact_values = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats()
    | st.text()
    | st.binary(),
    lambda children: (
        st.lists(children, max_size=5)
        | st.lists(children, max_size=5).map(tuple)
        | st.dictionaries(st.text(max_size=10), children, max_size=5)
    ),
    max_leaves=10,
)


def deep_equal(a, b):
    """Equality check that correctly handles NaN and -0.0."""
    if type(a) is not type(b):
        return False
    if isinstance(a, float):
        if math.isnan(a):
            return math.isnan(b)
        if a == 0.0 and b == 0.0:
            return math.copysign(1.0, a) == math.copysign(1.0, b)
        return a == b
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(deep_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(deep_equal(a[k], b[k]) for k in a)
    return a == b


# ---- Property 1: Roundtrip identity ----

@given(value=compact_values)
@settings(max_examples=500)
def test_roundtrip_identity(value):
    """encode then decode must return a value equal to the original."""
    encoded = encode(value)
    decoded = decode(encoded)
    assert deep_equal(decoded, value), (
        f"Roundtrip failed:\\n  original: {value!r}\\n  decoded:  {decoded!r}"
    )


@given(n=st.integers(min_value=-(2**128), max_value=2**128))
@settings(max_examples=300)
def test_large_integer_roundtrip(n):
    """Integers outside 64-bit range must still roundtrip."""
    assert decode(encode(n)) == n


@given(d=st.dictionaries(
    st.text(min_size=1, max_size=20),
    st.integers(),
    max_size=5,
))
def test_dict_with_unicode_keys_roundtrip(d):
    assert decode(encode(d)) == d


@given(elems=st.lists(
    st.integers() | st.text() | st.none(), min_size=0, max_size=8
))
def test_tuple_roundtrip(elems):
    t = tuple(elems)
    assert decode(encode(t)) == t


# ---- Property 2: Type and sign preservation ----

@given(f=st.floats())
def test_float_type_and_sign_preservation(f):
    """Decoded floats must preserve exact type and IEEE 754 sign bit."""
    result = decode(encode(f))
    assert isinstance(result, float)
    if math.isnan(f):
        assert math.isnan(result)
    else:
        assert result == f
        assert struct.pack(">d", result) == struct.pack(">d", f), (
            f"Bit-level mismatch for {f!r}"
        )


@given(value=compact_values)
@settings(max_examples=300)
def test_type_preservation(value):
    """Decoded value must have the exact same Python type as the original."""
    result = decode(encode(value))
    if isinstance(value, float) and math.isnan(value):
        assert isinstance(result, float) and math.isnan(result)
    elif isinstance(value, (list, tuple)):
        assert type(result) is type(value)
        assert len(result) == len(value)
    elif isinstance(value, dict):
        assert isinstance(result, dict)
        assert set(result.keys()) == set(value.keys())
    else:
        assert type(result) is type(value)


# ---- Property 3: Encoding determinism ----

@given(value=compact_values)
@settings(max_examples=200)
def test_encoding_determinism(value):
    """The same value must always produce the same byte sequence."""
    enc1 = encode(value)
    enc2 = encode(value)
    assert enc1 == enc2, "Encoding is not deterministic"
'''

os.makedirs('/app/tests', exist_ok=True)
with open('/app/tests/test_pbt.py', 'w') as f:
    f.write(pbt_code)

print('[solve] Wrote property-based tests to /app/tests/test_pbt.py')

# ---- Write bug taxonomy report ----
bug_report = [
    {
        "function": "_zigzag_encode",
        "root_cause": "Uses the fixed-width formula (n << 1) ^ (n >> 63) which assumes 64-bit two's complement arithmetic. Python integers have arbitrary precision, so n >> 63 evaluates to values other than 0 or -1 when |n| >= 2^63, producing incorrect zigzag mappings for large integers.",
        "trigger_input": "2**63",
        "property_type": "roundtrip identity"
    },
    {
        "function": "_encode_float",
        "root_cause": "The TAG_FLOAT_ZERO shorthand path checks `value == 0.0` without distinguishing the sign. In IEEE 754, -0.0 == 0.0 evaluates to True, so negative zero is encoded as TAG_FLOAT_ZERO and decoded as positive 0.0, losing the sign bit. The fix must use math.copysign to check the sign before taking the shorthand path.",
        "trigger_input": "-0.0",
        "property_type": "type and sign preservation"
    },
    {
        "function": "_decode_value (TAG_DICT branch)",
        "root_cause": "After decoding a dict key from UTF-8 bytes, position is advanced by len(key) (Python character count) instead of key_byte_len (the number of raw UTF-8 bytes). For non-ASCII keys (e.g. accented characters, CJK, emoji), the character count is less than the byte count, causing the decoder to under-advance and read subsequent data from the wrong offset.",
        "trigger_input": "{'caf\\u00e9': 1}",
        "property_type": "roundtrip identity"
    },
    {
        "function": "_encode_value (tuple branch)",
        "root_cause": "The encoder serializes tuple elements into a temporary inner_buf and then writes len(inner_buf) (the total serialized byte count) as the count prefix. The decoder interprets this count as the number of elements. For elements whose serialized form exceeds 1 byte (e.g. integers, strings), byte count > element count, causing the decoder to attempt reading more elements than exist.",
        "trigger_input": "(42,)",
        "property_type": "roundtrip identity"
    }
]

with open('/app/bug_report.json', 'w') as f:
    json.dump(bug_report, f, indent=2)

print('[solve] Wrote bug taxonomy to /app/bug_report.json')
