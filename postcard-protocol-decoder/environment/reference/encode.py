#!/usr/bin/env python3
"""Reference postcard wire format encoder for verification.

Usage:
  python3 encode.py <type> <value>
  python3 encode.py test-vectors

Outputs hex-encoded bytes to stdout.

Supported types:
  bool, u8, i8, u16, i16, u32, i32, u64, i64, f32, f64, string
  option:<inner_type>    e.g. option:u32
  seq:<element_type>     e.g. seq:u16      (value is JSON array)
  tuple:<t1>,<t2>,...    e.g. tuple:u8,u8,u8 (value is JSON array)
"""

import struct
import json
import sys


def encode_varint_unsigned(value):
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def zigzag_encode(value):
    if value >= 0:
        return value * 2
    else:
        return (-value) * 2 - 1


def encode_value(type_name, value):
    if type_name == 'bool':
        return bytes([0x01 if value else 0x00])
    elif type_name == 'u8':
        return bytes([int(value) & 0xFF])
    elif type_name == 'i8':
        return struct.pack('b', int(value))
    elif type_name in ('u16', 'u32', 'u64'):
        return encode_varint_unsigned(int(value))
    elif type_name in ('i16', 'i32', 'i64'):
        return encode_varint_unsigned(zigzag_encode(int(value)))
    elif type_name == 'f32':
        return struct.pack('<f', float(value))
    elif type_name == 'f64':
        return struct.pack('<d', float(value))
    elif type_name == 'string':
        b = str(value).encode('utf-8')
        return encode_varint_unsigned(len(b)) + b
    elif type_name.startswith('option:'):
        inner = type_name[7:]
        if value is None:
            return bytes([0x00])
        return bytes([0x01]) + encode_value(inner, value)
    elif type_name.startswith('seq:'):
        inner = type_name[4:]
        items = json.loads(value) if isinstance(value, str) else value
        result = bytearray(encode_varint_unsigned(len(items)))
        for item in items:
            result += encode_value(inner, item)
        return bytes(result)
    elif type_name.startswith('tuple:'):
        types = [t.strip() for t in type_name[6:].split(',')]
        items = json.loads(value) if isinstance(value, str) else value
        result = bytearray()
        for t, v in zip(types, items):
            result += encode_value(t, v)
        return bytes(result)
    else:
        raise ValueError(f"Unsupported type: {type_name}")


def to_hex(data):
    return ' '.join(f'{b:02x}' for b in data)


def print_test_vectors():
    vectors = [
        ("u16", 0),
        ("u16", 127),
        ("u16", 128),
        ("u16", 300),
        ("u16", 1023),
        ("u16", 16383),
        ("u16", 65535),
        ("u32", 86400),
        ("i16", 0),
        ("i16", -1),
        ("i16", 1),
        ("i16", -500),
        ("i16", -5),
        ("i32", 0),
        ("i32", -1),
        ("i32", 1),
        ("i32", -15),
        ("i32", 100),
        ("i64", 0),
        ("i64", -1),
        ("i64", 5000),
        ("f32", 65.5),
        ("f32", 0.0),
        ("f32", -1.0),
        ("bool", True),
        ("bool", False),
        ("u8", 0),
        ("u8", 3),
        ("u8", 255),
        ("string", "temp_a"),
        ("string", ""),
        ("string", "hello"),
        ("u64", 86400),
        ("u64", 5000),
        ("u64", 0),
    ]
    for type_name, value in vectors:
        encoded = encode_value(type_name, value)
        print(f"{type_name}({value}) = {to_hex(encoded)}")

    print("\n--- Composite types ---")
    composites = [
        ("seq:u16", [1, 257]),
        ("seq:u16", []),
        ("tuple:u8,u8,u8", [1, 4, 2]),
        ("tuple:u8,u8,u8", [0, 0, 1]),
        ("option:u32", None),
        ("option:u32", 2000),
    ]
    for type_name, value in composites:
        encoded = encode_value(type_name, value)
        print(f"{type_name}({json.dumps(value)}) = {to_hex(encoded)}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: encode.py <type> <value>")
        print("       encode.py test-vectors")
        print()
        print("Examples:")
        print("  python3 encode.py u16 1023")
        print("  python3 encode.py i32 -15")
        print("  python3 encode.py f32 65.5")
        print('  python3 encode.py string "temp_a"')
        print("  python3 encode.py option:u32 null")
        print("  python3 encode.py option:u32 42")
        print('  python3 encode.py seq:u16 "[1, 257]"')
        print('  python3 encode.py tuple:u8,u8,u8 "[1, 4, 2]"')
        sys.exit(1)

    if sys.argv[1] == 'test-vectors':
        print_test_vectors()
    else:
        type_name = sys.argv[1]
        raw_value = sys.argv[2] if len(sys.argv) > 2 else 'null'
        try:
            value = json.loads(raw_value)
        except (json.JSONDecodeError, ValueError):
            value = raw_value
        encoded = encode_value(type_name, value)
        print(to_hex(encoded))
