#!/usr/bin/env python3
"""Generate reference test vectors for postcard wire format verification."""

import struct
import os
import json


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


def cobs_encode(data):
    output = bytearray()
    code_idx = len(output)
    output.append(0)
    code = 1
    for byte in data:
        if byte == 0:
            output[code_idx] = code
            code_idx = len(output)
            output.append(0)
            code = 1
        else:
            output.append(byte)
            code += 1
            if code == 0xFF:
                output[code_idx] = code
                code_idx = len(output)
                output.append(0)
                code = 1
    output[code_idx] = code
    return bytes(output)


def crc8(data):
    """CRC-8 with polynomial 0x31, init=0x00."""
    crc = 0x00
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x31) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


os.makedirs('/app/test_vectors', exist_ok=True)

# --- Unsigned varint vectors ---
for name, value in [('varint_0', 0), ('varint_42', 42), ('varint_127', 127),
                    ('varint_128', 128), ('varint_300', 300),
                    ('varint_1023', 1023), ('varint_16383', 16383),
                    ('varint_65535', 65535), ('varint_86400', 86400)]:
    with open(f'/app/test_vectors/{name}.bin', 'wb') as f:
        f.write(encode_varint_unsigned(value))

# --- Zigzag + varint vectors ---
for name, value in [('zigzag_0', 0), ('zigzag_neg1', -1), ('zigzag_1', 1),
                    ('zigzag_neg15', -15), ('zigzag_15', 15),
                    ('zigzag_neg500', -500), ('zigzag_neg5', -5),
                    ('zigzag_100', 100), ('zigzag_5', 5)]:
    with open(f'/app/test_vectors/{name}.bin', 'wb') as f:
        f.write(encode_varint_unsigned(zigzag_encode(value)))

# --- IEEE 754 float vectors (little-endian) ---
for name, value in [('f32_65_5', 65.5), ('f32_0_0', 0.0),
                    ('f32_neg1_0', -1.0), ('f32_3_14', 3.140000104904175)]:
    with open(f'/app/test_vectors/{name}.bin', 'wb') as f:
        f.write(struct.pack('<f', value))

# --- Bool vectors ---
with open('/app/test_vectors/bool_true.bin', 'wb') as f:
    f.write(bytes([0x01]))
with open('/app/test_vectors/bool_false.bin', 'wb') as f:
    f.write(bytes([0x00]))

# --- String vectors ---
for name, value in [('string_temp_a', 'temp_a'), ('string_empty', ''),
                    ('string_hello', 'hello')]:
    with open(f'/app/test_vectors/{name}.bin', 'wb') as f:
        b = value.encode('utf-8')
        f.write(encode_varint_unsigned(len(b)) + b)

# --- Tuple vector (NO length prefix) ---
with open('/app/test_vectors/tuple_u8_1_4_2.bin', 'wb') as f:
    f.write(bytes([1, 4, 2]))

with open('/app/test_vectors/tuple_u8_0_0_1.bin', 'wb') as f:
    f.write(bytes([0, 0, 1]))

# --- Sequence vector (WITH length prefix) ---
with open('/app/test_vectors/seq_u16_1_257.bin', 'wb') as f:
    f.write(encode_varint_unsigned(2) +
            encode_varint_unsigned(1) +
            encode_varint_unsigned(257))

with open('/app/test_vectors/seq_u16_empty.bin', 'wb') as f:
    f.write(encode_varint_unsigned(0))

# --- Option vectors ---
with open('/app/test_vectors/option_none.bin', 'wb') as f:
    f.write(bytes([0x00]))

with open('/app/test_vectors/option_some_2000.bin', 'wb') as f:
    f.write(bytes([0x01]) + encode_varint_unsigned(2000))

# --- Map vector ---
with open('/app/test_vectors/map_empty.bin', 'wb') as f:
    f.write(encode_varint_unsigned(0))

# --- Enum struct variant vector ---
with open('/app/test_vectors/enum_struct_variant.bin', 'wb') as f:
    data = encode_varint_unsigned(2)              # discriminant 2
    data += encode_varint_unsigned(1001)           # code: u16
    data += encode_varint_unsigned(4) + b'test'    # detail: string
    data += bytes([0x00])                          # recoverable: bool(false)
    f.write(data)

# --- Enum unit variant vector ---
with open('/app/test_vectors/enum_unit_variant_0.bin', 'wb') as f:
    f.write(encode_varint_unsigned(0))

# --- Enum newtype variant vector ---
with open('/app/test_vectors/enum_newtype_variant.bin', 'wb') as f:
    data = encode_varint_unsigned(1)              # discriminant 1
    data += encode_varint_unsigned(5) + b'hello'  # inner string
    f.write(data)

# --- COBS vector ---
with open('/app/test_vectors/cobs_simple.bin', 'wb') as f:
    payload = bytes([0x01, 0x02, 0x00, 0x03])
    f.write(cobs_encode(payload) + b'\x00')

with open('/app/test_vectors/cobs_no_zeros.bin', 'wb') as f:
    payload = bytes([0x01, 0x02, 0x03, 0x04])
    f.write(cobs_encode(payload) + b'\x00')

with open('/app/test_vectors/cobs_all_zeros.bin', 'wb') as f:
    payload = bytes([0x00, 0x00, 0x00])
    f.write(cobs_encode(payload) + b'\x00')

# --- CRC-8 test vectors (polynomial 0x31) ---
crc8_vectors = [
    ('crc8_abc', bytes([0x61, 0x62, 0x63])),
    ('crc8_zeros', bytes([0x00, 0x00, 0x00])),
    ('crc8_single_ff', bytes([0xFF])),
    ('crc8_sequential', bytes(range(10))),
]
for name, payload in crc8_vectors:
    computed = crc8(payload)
    with open(f'/app/test_vectors/{name}.bin', 'wb') as f:
        f.write(payload + bytes([computed]))

# --- Manifest ---
manifest = {
    "description": "Reference binary encodings of known values. "
                   "Use binary inspection tools (xxd, od) to analyze byte patterns "
                   "and verify your decoder implementation.",
    "vectors": [
        {"file": "varint_0.bin", "value": 0, "type": "unsigned varint"},
        {"file": "varint_42.bin", "value": 42, "type": "unsigned varint"},
        {"file": "varint_127.bin", "value": 127, "type": "unsigned varint"},
        {"file": "varint_128.bin", "value": 128, "type": "unsigned varint"},
        {"file": "varint_300.bin", "value": 300, "type": "unsigned varint"},
        {"file": "varint_1023.bin", "value": 1023, "type": "unsigned varint"},
        {"file": "varint_16383.bin", "value": 16383, "type": "unsigned varint"},
        {"file": "varint_65535.bin", "value": 65535, "type": "unsigned varint"},
        {"file": "varint_86400.bin", "value": 86400, "type": "unsigned varint"},
        {"file": "zigzag_0.bin", "value": 0, "type": "signed integer (zigzag + varint)"},
        {"file": "zigzag_neg1.bin", "value": -1, "type": "signed integer (zigzag + varint)"},
        {"file": "zigzag_1.bin", "value": 1, "type": "signed integer (zigzag + varint)"},
        {"file": "zigzag_neg15.bin", "value": -15, "type": "signed integer (zigzag + varint)"},
        {"file": "zigzag_15.bin", "value": 15, "type": "signed integer (zigzag + varint)"},
        {"file": "zigzag_neg500.bin", "value": -500, "type": "signed integer (zigzag + varint)"},
        {"file": "zigzag_neg5.bin", "value": -5, "type": "signed integer (zigzag + varint)"},
        {"file": "zigzag_100.bin", "value": 100, "type": "signed integer (zigzag + varint)"},
        {"file": "zigzag_5.bin", "value": 5, "type": "signed integer (zigzag + varint)"},
        {"file": "f32_65_5.bin", "value": 65.5, "type": "f32 IEEE 754 little-endian"},
        {"file": "f32_0_0.bin", "value": 0.0, "type": "f32 IEEE 754 little-endian"},
        {"file": "f32_neg1_0.bin", "value": -1.0, "type": "f32 IEEE 754 little-endian"},
        {"file": "f32_3_14.bin", "value": 3.14, "type": "f32 IEEE 754 little-endian (note: f32 precision)"},
        {"file": "bool_true.bin", "value": True, "type": "bool"},
        {"file": "bool_false.bin", "value": False, "type": "bool"},
        {"file": "string_temp_a.bin", "value": "temp_a", "type": "varint-prefixed UTF-8 string"},
        {"file": "string_empty.bin", "value": "", "type": "varint-prefixed UTF-8 string"},
        {"file": "string_hello.bin", "value": "hello", "type": "varint-prefixed UTF-8 string"},
        {"file": "tuple_u8_1_4_2.bin", "value": [1, 4, 2], "type": "tuple(u8, u8, u8) — NO length prefix"},
        {"file": "tuple_u8_0_0_1.bin", "value": [0, 0, 1], "type": "tuple(u8, u8, u8) — NO length prefix"},
        {"file": "seq_u16_1_257.bin", "value": [1, 257], "type": "seq<u16> — WITH varint length prefix"},
        {"file": "seq_u16_empty.bin", "value": [], "type": "seq<u16> — WITH varint length prefix"},
        {"file": "option_none.bin", "value": None, "type": "Option — None"},
        {"file": "option_some_2000.bin", "value": 2000, "type": "Option<u32> — Some(2000)"},
        {"file": "map_empty.bin", "value": {}, "type": "Map — empty"},
        {"file": "enum_unit_variant_0.bin", "value": "variant index 0", "type": "enum unit variant (discriminant only)"},
        {"file": "enum_newtype_variant.bin", "value": {"variant_index": 1, "inner": "hello"}, "type": "enum newtype variant (discriminant + value)"},
        {"file": "enum_struct_variant.bin",
         "value": {"variant_index": 2, "fields": {"code": 1001, "detail": "test", "recoverable": False}},
         "type": "enum struct variant (discriminant + named fields in order)"},
        {"file": "cobs_simple.bin", "value": [1, 2, 0, 3], "type": "COBS encoded payload + 0x00 delimiter"},
        {"file": "cobs_no_zeros.bin", "value": [1, 2, 3, 4], "type": "COBS encoded payload with no zeros"},
        {"file": "cobs_all_zeros.bin", "value": [0, 0, 0], "type": "COBS encoded payload of all zeros"},
        {"file": "crc8_abc.bin", "value": "abc (0x61,0x62,0x63) + CRC byte", "type": "CRC-8 test: 3-byte payload with appended checksum"},
        {"file": "crc8_zeros.bin", "value": "three zero bytes + CRC byte", "type": "CRC-8 test: all-zeros payload"},
        {"file": "crc8_single_ff.bin", "value": "0xFF + CRC byte", "type": "CRC-8 test: single 0xFF byte"},
        {"file": "crc8_sequential.bin", "value": "bytes 0x00..0x09 + CRC byte", "type": "CRC-8 test: sequential bytes"}
    ]
}

with open('/app/test_vectors/manifest.json', 'w') as f:
    json.dump(manifest, f, indent=2)

print("Generated test vectors successfully.")
