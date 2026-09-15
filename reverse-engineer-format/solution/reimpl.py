#!/usr/bin/env python3
"""
RPACK v1 binary serialization format - reimplementation.

Reverse-engineered from /app/oracle binary.

Format:
  Header: 0xCF 0xB0 0x01 (3 bytes)
  Body:   recursive tagged values
  Footer: CRC-8 (polynomial 0x07, init 0) of header+body

Type tags:
  0x00        null
  0x01        false
  0x02        true
  0x10-0x1F   fixint 0-15 (value = tag - 0x10)
  0x20        int8  (1 byte signed)
  0x21        int16 (2 bytes LE signed)
  0x22        int32 (4 bytes LE signed)
  0x23        int64 (8 bytes LE signed)
  0x30        float64 (8 bytes big-endian IEEE 754)
  0x40        string (varint byte-length + raw UTF-8)
  0x50        array  (varint count + N tagged values)
  0x60        object (varint count + N key-value pairs, sorted by key;
                      key = varint-len + raw bytes, value = tagged)

Integers use the smallest encoding that fits.
Integers are little-endian; floats are big-endian.
Varint is unsigned LEB128 (7 bits/byte, MSB=1 continues).
"""
import sys
import json
import struct
import math


# ---------- CRC-8 (polynomial 0x07, init 0) ----------

def crc8(data):
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x07) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


# ---------- LEB128 varint ----------

def encode_varint(v):
    out = bytearray()
    while True:
        byte = v & 0x7F
        v >>= 7
        if v:
            byte |= 0x80
        out.append(byte)
        if not v:
            break
    return bytes(out)


def decode_varint(data, pos):
    result = 0
    shift = 0
    while pos < len(data):
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            break
        shift += 7
    return result, pos


# ---------- Encode ----------

def encode_value(value):
    buf = bytearray()

    if value is None:
        buf.append(0x00)
    elif isinstance(value, bool):
        buf.append(0x02 if value else 0x01)
    elif isinstance(value, (int, float)):
        d = float(value)
        if (math.floor(d) == d and not math.isinf(d) and not math.isnan(d)
                and -9007199254740992 <= d <= 9007199254740992):
            n = int(d)
            if 0 <= n <= 15:
                buf.append(0x10 + n)
            elif -128 <= n <= 127:
                buf.append(0x20)
                buf.extend(struct.pack('b', n))
            elif -32768 <= n <= 32767:
                buf.append(0x21)
                buf.extend(struct.pack('<h', n))
            elif -2147483648 <= n <= 2147483647:
                buf.append(0x22)
                buf.extend(struct.pack('<i', n))
            else:
                buf.append(0x23)
                buf.extend(struct.pack('<q', n))
        else:
            buf.append(0x30)
            buf.extend(struct.pack('>d', d))
    elif isinstance(value, str):
        buf.append(0x40)
        raw = value.encode('utf-8')
        buf.extend(encode_varint(len(raw)))
        buf.extend(raw)
    elif isinstance(value, list):
        buf.append(0x50)
        buf.extend(encode_varint(len(value)))
        for item in value:
            buf.extend(encode_value(item))
    elif isinstance(value, dict):
        buf.append(0x60)
        sorted_keys = sorted(value.keys())
        buf.extend(encode_varint(len(sorted_keys)))
        for key in sorted_keys:
            key_bytes = key.encode('utf-8')
            buf.extend(encode_varint(len(key_bytes)))
            buf.extend(key_bytes)
            buf.extend(encode_value(value[key]))

    return bytes(buf)


def encode_json(json_str):
    value = json.loads(json_str)
    header = bytes([0xCF, 0xB0, 0x01])
    body = encode_value(value)
    data = header + body
    return data + bytes([crc8(data)])


# ---------- Decode ----------

def decode_value(data, pos):
    tag = data[pos]
    pos += 1

    if tag == 0x00:
        return None, pos
    if tag == 0x01:
        return False, pos
    if tag == 0x02:
        return True, pos
    if 0x10 <= tag <= 0x1F:
        return tag - 0x10, pos
    if tag == 0x20:
        n = struct.unpack_from('b', data, pos)[0]
        return n, pos + 1
    if tag == 0x21:
        n = struct.unpack_from('<h', data, pos)[0]
        return n, pos + 2
    if tag == 0x22:
        n = struct.unpack_from('<i', data, pos)[0]
        return n, pos + 4
    if tag == 0x23:
        n = struct.unpack_from('<q', data, pos)[0]
        return n, pos + 8
    if tag == 0x30:
        d = struct.unpack_from('>d', data, pos)[0]
        return d, pos + 8
    if tag == 0x40:
        slen, pos = decode_varint(data, pos)
        s = data[pos:pos + slen].decode('utf-8')
        return s, pos + slen
    if tag == 0x50:
        count, pos = decode_varint(data, pos)
        arr = []
        for _ in range(count):
            val, pos = decode_value(data, pos)
            arr.append(val)
        return arr, pos
    if tag == 0x60:
        count, pos = decode_varint(data, pos)
        obj = {}
        for _ in range(count):
            klen, pos = decode_varint(data, pos)
            key = data[pos:pos + klen].decode('utf-8')
            pos += klen
            val, pos = decode_value(data, pos)
            obj[key] = val
        return obj, pos

    raise ValueError(f"Unknown tag: 0x{tag:02X}")


def decode_binary(data, check_trailing=False):
    if len(data) < 4 or data[0] != 0xCF or data[1] != 0xB0 or data[2] != 0x01:
        raise ValueError("bad header")
    expected_crc = data[-1]
    actual_crc = crc8(data[:-1])
    if expected_crc != actual_crc:
        raise ValueError("CRC mismatch")
    value, pos = decode_value(data, 3)
    if check_trailing and pos != len(data) - 1:
        raise ValueError("trailing data")
    return value


# ---------- JSON output (matching oracle format exactly) ----------

def format_json(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if (math.floor(value) == value and not math.isinf(value)
                and not math.isnan(value)
                and abs(value) <= 9007199254740992):
            return str(int(value))
        return f"{value:.17g}"
    if isinstance(value, str):
        result = ['"']
        for c in value:
            o = ord(c)
            if c == '"':
                result.append('\\"')
            elif c == '\\':
                result.append('\\\\')
            elif c == '\n':
                result.append('\\n')
            elif c == '\r':
                result.append('\\r')
            elif c == '\t':
                result.append('\\t')
            elif c == '\b':
                result.append('\\b')
            elif c == '\f':
                result.append('\\f')
            elif o < 0x20:
                result.append(f'\\u{o:04x}')
            else:
                result.append(c)
        result.append('"')
        return ''.join(result)
    if isinstance(value, list):
        return '[' + ','.join(format_json(item) for item in value) + ']'
    if isinstance(value, dict):
        pairs = []
        for key in value:
            pairs.append(format_json(key) + ':' + format_json(value[key]))
        return '{' + ','.join(pairs) + '}'
    raise TypeError(f"Cannot format: {type(value)}")


# ---------- Main ----------

def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} encode|decode|validate", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    data = sys.stdin.buffer.read()

    if cmd == "encode":
        result = encode_json(data.decode('utf-8'))
        sys.stdout.buffer.write(result)
    elif cmd == "decode":
        try:
            value = decode_binary(data)
            sys.stdout.write(format_json(value) + '\n')
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    elif cmd == "validate":
        try:
            decode_binary(data, check_trailing=True)
            print("VALID")
        except ValueError as e:
            print(f"INVALID: {e}")
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
