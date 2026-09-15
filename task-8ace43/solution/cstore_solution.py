#!/usr/bin/env python3
"""
CStore binary codec - Python reimplementation.
Custom binary serialization format for JSON data.

"""
import json
import struct
import sys
import os
import zlib


# ======================== CRC32 with salt ========================

def compute_crc(data):
    """CRC32 with optional CSTORE_SALT seed modification.
    When CSTORE_SALT is set, each byte of the salt is XORed into the
    CRC seed (0xFFFFFFFF) at rotating 8-bit positions (i % 4 * 8)."""
    salt = os.environ.get("CSTORE_SALT", "")
    if salt:
        seed = 0xFFFFFFFF
        for i, ch in enumerate(salt):
            seed ^= (ord(ch) << ((i % 4) * 8))
            seed &= 0xFFFFFFFF
        # zlib.crc32(data, value) internally does: crc = value ^ 0xFFFFFFFF
        # We need crc to start at 'seed', so value = seed ^ 0xFFFFFFFF
        init = (seed ^ 0xFFFFFFFF) & 0xFFFFFFFF
        return zlib.crc32(data, init) & 0xFFFFFFFF
    return zlib.crc32(data) & 0xFFFFFFFF


# ======================== Varint ========================

def encode_varint(val):
    """Unsigned varint: 7-bit groups, MSB continuation, little-endian."""
    result = bytearray()
    while True:
        byte = val & 0x7F
        val >>= 7
        if val:
            byte |= 0x80
        result.append(byte)
        if not val:
            break
    return bytes(result)


def decode_varint(data, pos):
    """Returns (value, new_pos)."""
    result = 0
    shift = 0
    while pos < len(data):
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, pos
        shift += 7
        if shift >= 64:
            raise ValueError("varint overflow")
    raise ValueError("truncated varint")


# ======================== Zigzag ========================

def zigzag_encode(n):
    """Signed int64 -> unsigned zigzag."""
    return (n << 1) ^ (n >> 63)


def zigzag_decode(n):
    """Unsigned zigzag -> signed int64."""
    return (n >> 1) ^ -(n & 1)


# ======================== Type Tags ========================

TAG_NULL = 0x00
TAG_FALSE = 0x01
TAG_TRUE = 0x02
TAG_INT = 0x03
TAG_FLOAT = 0x04
TAG_STRING = 0x05
TAG_ARRAY = 0x06
TAG_OBJECT = 0x07

MAGIC = b"CST\x01"


# ======================== Value wrapper ========================

class Val:
    """Wraps a decoded value with its original type tag."""
    def __init__(self, tag, value):
        self.tag = tag
        self.value = value


# ======================== Encoder ========================

def encode_value(val):
    """Encode a Python value (from json.loads) to CStore bytes."""
    if val is None:
        return bytes([TAG_NULL])
    elif isinstance(val, bool):
        return bytes([TAG_TRUE if val else TAG_FALSE])
    elif isinstance(val, int):
        # Check int64 range
        if -(1 << 63) <= val < (1 << 63):
            zz = zigzag_encode(val) & 0xFFFFFFFFFFFFFFFF
            return bytes([TAG_INT]) + encode_varint(zz)
        else:
            # Overflow: encode as float
            return _encode_float(float(val))
    elif isinstance(val, float):
        return _encode_float(val)
    elif isinstance(val, str):
        encoded = val.encode("utf-8")
        return bytes([TAG_STRING]) + encode_varint(len(encoded)) + encoded
    elif isinstance(val, list):
        parts = [bytes([TAG_ARRAY]), encode_varint(len(val))]
        for item in val:
            parts.append(encode_value(item))
        return b"".join(parts)
    elif isinstance(val, dict):
        # Sort keys by raw UTF-8 bytes
        sorted_keys = sorted(val.keys(), key=lambda k: k.encode("utf-8"))
        parts = [bytes([TAG_OBJECT]), encode_varint(len(sorted_keys))]
        for k in sorted_keys:
            k_bytes = k.encode("utf-8")
            parts.append(encode_varint(len(k_bytes)))
            parts.append(k_bytes)
            parts.append(encode_value(val[k]))
        return b"".join(parts)
    else:
        raise ValueError(f"Unsupported type: {type(val)}")


def _encode_float(d):
    """Encode a float64 value."""
    # Normalize -0.0 to +0.0
    if d == 0.0:
        d = 0.0
    return bytes([TAG_FLOAT]) + struct.pack(">d", d)


def cmd_encode(input_data):
    """Read JSON from input, write CStore to stdout."""
    text = input_data.decode("utf-8")
    val = json.loads(text)
    body = encode_value(val)
    header = MAGIC
    payload = header + body
    crc = compute_crc(payload)
    crc_bytes = struct.pack(">I", crc)
    sys.stdout.buffer.write(payload + crc_bytes)


# ======================== Decoder ========================

def decode_value(data, pos):
    """Decode a CStore value. Returns (Val, new_pos)."""
    if pos >= len(data):
        raise ValueError("unexpected end of data")
    tag = data[pos]
    pos += 1

    if tag == TAG_NULL:
        return Val(TAG_NULL, None), pos
    elif tag == TAG_FALSE:
        return Val(TAG_FALSE, False), pos
    elif tag == TAG_TRUE:
        return Val(TAG_TRUE, True), pos
    elif tag == TAG_INT:
        zz, pos = decode_varint(data, pos)
        return Val(TAG_INT, zigzag_decode(zz)), pos
    elif tag == TAG_FLOAT:
        if pos + 8 > len(data):
            raise ValueError("truncated float")
        d = struct.unpack(">d", data[pos : pos + 8])[0]
        pos += 8
        return Val(TAG_FLOAT, d), pos
    elif tag == TAG_STRING:
        slen, pos = decode_varint(data, pos)
        if pos + slen > len(data):
            raise ValueError("truncated string")
        s = data[pos : pos + slen].decode("utf-8")
        pos += slen
        return Val(TAG_STRING, s), pos
    elif tag == TAG_ARRAY:
        count, pos = decode_varint(data, pos)
        items = []
        for _ in range(count):
            item, pos = decode_value(data, pos)
            items.append(item)
        return Val(TAG_ARRAY, items), pos
    elif tag == TAG_OBJECT:
        count, pos = decode_varint(data, pos)
        pairs = []
        for _ in range(count):
            kl, pos = decode_varint(data, pos)
            if pos + kl > len(data):
                raise ValueError("truncated key")
            key = data[pos : pos + kl].decode("utf-8")
            pos += kl
            val, pos = decode_value(data, pos)
            pairs.append((key, val))
        return Val(TAG_OBJECT, pairs), pos
    else:
        raise ValueError(f"unknown tag 0x{tag:02x}")


# ======================== JSON Output ========================

def escape_string(s):
    """JSON-escape a string matching reference output."""
    result = ['"']
    for ch in s:
        o = ord(ch)
        if ch == '"':
            result.append('\\"')
        elif ch == '\\':
            result.append('\\\\')
        elif ch == '\b':
            result.append('\\b')
        elif ch == '\f':
            result.append('\\f')
        elif ch == '\n':
            result.append('\\n')
        elif ch == '\r':
            result.append('\\r')
        elif ch == '\t':
            result.append('\\t')
        elif o < 0x20:
            result.append(f"\\u{o:04x}")
        else:
            result.append(ch)
    result.append('"')
    return "".join(result)


def format_json(val, indent=0):
    """Format a decoded Val as JSON string matching reference output."""
    sp = "  " * indent

    if val.tag == TAG_NULL:
        return "null"
    elif val.tag in (TAG_FALSE, TAG_TRUE):
        return "true" if val.value else "false"
    elif val.tag == TAG_INT:
        return str(val.value)
    elif val.tag == TAG_FLOAT:
        s = f"{val.value:.17g}"
        if "." not in s and "e" not in s and "E" not in s:
            s += ".0"
        return s
    elif val.tag == TAG_STRING:
        return escape_string(val.value)
    elif val.tag == TAG_ARRAY:
        if not val.value:
            return "[]"
        lines = []
        lines.append("[\n")
        for i, item in enumerate(val.value):
            line = "  " * (indent + 1) + format_json(item, indent + 1)
            if i + 1 < len(val.value):
                line += ","
            line += "\n"
            lines.append(line)
        lines.append(sp + "]")
        return "".join(lines)
    elif val.tag == TAG_OBJECT:
        if not val.value:
            return "{}"
        lines = []
        lines.append("{\n")
        for i, (key, v) in enumerate(val.value):
            line = "  " * (indent + 1) + escape_string(key) + ": " + format_json(v, indent + 1)
            if i + 1 < len(val.value):
                line += ","
            line += "\n"
            lines.append(line)
        lines.append(sp + "}")
        return "".join(lines)
    else:
        raise ValueError(f"Unknown tag: {val.tag}")


def cmd_decode(input_data):
    """Read CStore from input, write JSON to stdout."""
    data = input_data
    if len(data) < 9:
        print("file too small", file=sys.stderr)
        sys.exit(1)
    if data[:4] != MAGIC:
        print("bad magic", file=sys.stderr)
        sys.exit(1)

    stored_crc = struct.unpack(">I", data[-4:])[0]
    calc_crc = compute_crc(data[:-4])
    if stored_crc != calc_crc:
        print("CRC mismatch", file=sys.stderr)
        sys.exit(1)

    body = data[4:-4]
    val, pos = decode_value(body, 0)
    if pos != len(body):
        print("trailing data in CStore", file=sys.stderr)
        sys.exit(1)

    output = format_json(val, 0) + "\n"
    sys.stdout.write(output)


# ======================== Info ========================

def count_values(val):
    """Count total number of values."""
    c = 1
    if val.tag == TAG_ARRAY:
        for item in val.value:
            c += count_values(item)
    elif val.tag == TAG_OBJECT:
        for _, v in val.value:
            c += count_values(v)
    return c


def max_depth(val):
    """Maximum nesting depth."""
    md = 1
    if val.tag == TAG_ARRAY:
        for item in val.value:
            d = 1 + max_depth(item)
            if d > md:
                md = d
    elif val.tag == TAG_OBJECT:
        for _, v in val.value:
            d = 1 + max_depth(v)
            if d > md:
                md = d
    return md


def type_name(tag):
    names = {
        TAG_NULL: "null",
        TAG_FALSE: "boolean",
        TAG_TRUE: "boolean",
        TAG_INT: "integer",
        TAG_FLOAT: "float",
        TAG_STRING: "string",
        TAG_ARRAY: "array",
        TAG_OBJECT: "object",
    }
    return names.get(tag, "unknown")


def cmd_info(input_data):
    """Read CStore from input, write info to stdout."""
    data = input_data
    if len(data) < 9:
        print("file too small", file=sys.stderr)
        sys.exit(1)
    if data[:4] != MAGIC:
        print("bad magic", file=sys.stderr)
        sys.exit(1)

    stored_crc = struct.unpack(">I", data[-4:])[0]
    calc_crc = compute_crc(data[:-4])

    body = data[4:-4]
    val, _ = decode_value(body, 0)

    print("CStore v1")
    print(f"Size: {len(data)} bytes")
    print(f"Root: {type_name(val.tag)}")
    print(f"Values: {count_values(val)}")
    print(f"Depth: {max_depth(val)}")
    print(f"CRC32: {calc_crc:08x}")
    print(f"Status: {'OK' if stored_crc == calc_crc else 'INVALID'}")


# ======================== Main ========================

def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <encode|decode|info>", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    input_data = sys.stdin.buffer.read()

    if cmd == "encode":
        cmd_encode(input_data)
    elif cmd == "decode":
        cmd_decode(input_data)
    elif cmd == "info":
        cmd_info(input_data)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
