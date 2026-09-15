"""Compact binary serialization codec.

Supports the following Python types:
  None, bool, int, float, str, bytes, list, tuple, dict (string keys only).

Wire format
-----------
Each value is preceded by a one-byte type tag.  Integers use zigzag
encoding followed by an unsigned varint.  Lengths and counts are
unsigned varints.  Floats are big-endian IEEE-754, with shorthand tags
for 0.0, +/-inf and NaN.
"""

import struct
import math

from .varint import encode_varint, decode_varint

# ---- type tags ----
TAG_NONE       = 0x00
TAG_FALSE      = 0x01
TAG_TRUE       = 0x02
TAG_INT        = 0x03
TAG_FLOAT      = 0x04
TAG_FLOAT_ZERO = 0x05
TAG_STRING     = 0x06
TAG_BYTES      = 0x07
TAG_LIST       = 0x08
TAG_DICT       = 0x09
TAG_TUPLE      = 0x0A
TAG_FLOAT_INF  = 0x0B
TAG_FLOAT_NAN  = 0x0C


# --------------------------------------------------------------------
# zigzag helpers
# --------------------------------------------------------------------

def _zigzag_encode(n: int) -> int:
    """Map a signed integer to an unsigned integer.

    Mapping: 0 -> 0, -1 -> 1, 1 -> 2, -2 -> 3, 2 -> 4, ...
    """
    return (n << 1) ^ (n >> 63)


def _zigzag_decode(z: int) -> int:
    """Reverse the zigzag mapping."""
    return (z >> 1) ^ -(z & 1)


# --------------------------------------------------------------------
# encoder
# --------------------------------------------------------------------

def encode(value) -> bytes:
    """Serialize *value* to compact binary format."""
    buf = bytearray()
    _encode_value(buf, value)
    return bytes(buf)


def _encode_value(buf: bytearray, value) -> None:
    if value is None:
        buf.append(TAG_NONE)

    elif isinstance(value, bool):
        # bool must be checked before int (bool is a subclass of int)
        buf.append(TAG_TRUE if value else TAG_FALSE)

    elif isinstance(value, int):
        buf.append(TAG_INT)
        z = _zigzag_encode(value)
        buf.extend(encode_varint(z))

    elif isinstance(value, float):
        _encode_float(buf, value)

    elif isinstance(value, str):
        buf.append(TAG_STRING)
        raw = value.encode('utf-8')
        buf.extend(encode_varint(len(raw)))
        buf.extend(raw)

    elif isinstance(value, bytes):
        buf.append(TAG_BYTES)
        buf.extend(encode_varint(len(value)))
        buf.extend(value)

    elif isinstance(value, list):
        buf.append(TAG_LIST)
        buf.extend(encode_varint(len(value)))
        for item in value:
            _encode_value(buf, item)

    elif isinstance(value, tuple):
        buf.append(TAG_TUPLE)
        # Serialize elements into a temporary buffer so we can prefix
        # the total serialized size for efficient skipping.
        inner_buf = bytearray()
        for item in value:
            _encode_value(inner_buf, item)
        buf.extend(encode_varint(len(inner_buf)))
        buf.extend(inner_buf)

    elif isinstance(value, dict):
        buf.append(TAG_DICT)
        buf.extend(encode_varint(len(value)))
        for key, val in value.items():
            if not isinstance(key, str):
                raise TypeError(
                    f"Dict keys must be strings, got {type(key).__name__}"
                )
            key_raw = key.encode('utf-8')
            buf.extend(encode_varint(len(key_raw)))
            buf.extend(key_raw)
            _encode_value(buf, val)

    else:
        raise TypeError(f"Unsupported type: {type(value).__name__}")


def _encode_float(buf: bytearray, value: float) -> None:
    """Encode a float, using compact tags for common special values."""
    if math.isnan(value):
        buf.append(TAG_FLOAT_NAN)
    elif math.isinf(value):
        buf.append(TAG_FLOAT_INF)
        buf.append(0x00 if value > 0 else 0x01)
    elif value == 0.0:
        buf.append(TAG_FLOAT_ZERO)
    else:
        buf.append(TAG_FLOAT)
        buf.extend(struct.pack('>d', value))


# --------------------------------------------------------------------
# decoder
# --------------------------------------------------------------------

def decode(data: bytes):
    """Deserialize compact binary *data* back to a Python value."""
    if not isinstance(data, bytes):
        raise TypeError(f"Expected bytes, got {type(data).__name__}")
    if len(data) == 0:
        raise ValueError("Empty data")
    value, pos = _decode_value(data, 0)
    if pos != len(data):
        raise ValueError(
            f"Trailing data: {len(data) - pos} extra byte(s) at position {pos}"
        )
    return value


def _decode_value(data: bytes, pos: int) -> tuple:
    if pos >= len(data):
        raise ValueError("Unexpected end of data")

    tag = data[pos]
    pos += 1

    if tag == TAG_NONE:
        return None, pos

    elif tag == TAG_FALSE:
        return False, pos

    elif tag == TAG_TRUE:
        return True, pos

    elif tag == TAG_INT:
        z, pos = decode_varint(data, pos)
        return _zigzag_decode(z), pos

    elif tag == TAG_FLOAT:
        if pos + 8 > len(data):
            raise ValueError("Unexpected end of data reading float64")
        value = struct.unpack('>d', data[pos:pos + 8])[0]
        return value, pos + 8

    elif tag == TAG_FLOAT_ZERO:
        return 0.0, pos

    elif tag == TAG_FLOAT_INF:
        if pos >= len(data):
            raise ValueError("Unexpected end of data reading infinity sign")
        sign = data[pos]
        pos += 1
        return float('-inf') if sign else float('inf'), pos

    elif tag == TAG_FLOAT_NAN:
        return float('nan'), pos

    elif tag == TAG_STRING:
        byte_len, pos = decode_varint(data, pos)
        if pos + byte_len > len(data):
            raise ValueError("Unexpected end of data reading string")
        raw = data[pos:pos + byte_len]
        text = raw.decode('utf-8')
        pos += byte_len
        return text, pos

    elif tag == TAG_BYTES:
        length, pos = decode_varint(data, pos)
        if pos + length > len(data):
            raise ValueError("Unexpected end of data reading bytes")
        value = data[pos:pos + length]
        return bytes(value), pos + length

    elif tag == TAG_LIST:
        count, pos = decode_varint(data, pos)
        result = []
        for _ in range(count):
            item, pos = _decode_value(data, pos)
            result.append(item)
        return result, pos

    elif tag == TAG_TUPLE:
        count, pos = decode_varint(data, pos)
        result = []
        for _ in range(count):
            item, pos = _decode_value(data, pos)
            result.append(item)
        return tuple(result), pos

    elif tag == TAG_DICT:
        count, pos = decode_varint(data, pos)
        result = {}
        for _ in range(count):
            key_byte_len, pos = decode_varint(data, pos)
            if pos + key_byte_len > len(data):
                raise ValueError("Unexpected end of data reading dict key")
            key_raw = data[pos:pos + key_byte_len]
            key = key_raw.decode('utf-8')
            pos += len(key)
            val, pos = _decode_value(data, pos)
            result[key] = val
        return result, pos

    else:
        raise ValueError(f"Unknown type tag: 0x{tag:02x}")
