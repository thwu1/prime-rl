#!/usr/bin/env python3

"""
Postcard wire format decoder with COBS deframing.
Reads /app/capture.bin and produces /app/report.json.
Schema derived from firmware/src/types.rs.
"""

import json
import struct
import sys


# Message schema matching the Rust type definitions in firmware/src/types.rs.
# Discriminant values correspond to variant declaration order (0-indexed).
SCHEMA = {
    "root_type": "Message",
    "types": {
        "Message": {
            "kind": "enum",
            "variants": [
                {
                    "discriminant": 0,
                    "name": "SensorReading",
                    "fields": [
                        {"name": "sensor_id", "type": "u16"},
                        {"name": "timestamp", "type": "u32"},
                        {"name": "values", "type": {"seq": "f32"}},
                        {"name": "status", "type": {"option": "StatusCode"}}
                    ]
                },
                {
                    "discriminant": 1,
                    "name": "ConfigUpdate",
                    "fields": [
                        {"name": "param_id", "type": "u16"},
                        {"name": "value", "type": "ConfigValue"}
                    ]
                },
                {
                    "discriminant": 2,
                    "name": "Heartbeat",
                    "fields": [
                        {"name": "uptime_ms", "type": "u64"},
                        {"name": "free_mem", "type": "u32"}
                    ]
                },
                {
                    "discriminant": 3,
                    "name": "Alert",
                    "fields": [
                        {"name": "level", "type": "AlertLevel"},
                        {"name": "source", "type": "string"},
                        {"name": "code", "type": "u32"}
                    ]
                }
            ]
        },
        "StatusCode": {
            "kind": "enum",
            "variants": [
                {"discriminant": 0, "name": "Ok", "fields": []},
                {"discriminant": 1, "name": "Warning", "fields": [{"name": "code", "type": "u8"}]},
                {"discriminant": 2, "name": "Error", "fields": [{"name": "code", "type": "u16"}]}
            ]
        },
        "ConfigValue": {
            "kind": "enum",
            "variants": [
                {"discriminant": 0, "name": "Int", "fields": [{"name": "value", "type": "i32"}]},
                {"discriminant": 1, "name": "Float", "fields": [{"name": "value", "type": "f32"}]},
                {"discriminant": 2, "name": "Str", "fields": [{"name": "value", "type": "string"}]},
                {"discriminant": 3, "name": "Bool", "fields": [{"name": "value", "type": "bool"}]}
            ]
        },
        "AlertLevel": {
            "kind": "enum",
            "variants": [
                {"discriminant": 0, "name": "Info", "fields": []},
                {"discriminant": 1, "name": "Warn", "fields": []},
                {"discriminant": 2, "name": "Critical", "fields": []}
            ]
        }
    }
}


class DecodeError(Exception):
    """Error during message decoding with classification."""
    def __init__(self, error_type, detail=""):
        self.error_type = error_type
        self.detail = detail
        super().__init__(f"{error_type}: {detail}")


class ByteReader:
    """Tracks position in a byte buffer for sequential reading."""
    def __init__(self, data):
        self.data = bytes(data)
        self.pos = 0

    def remaining(self):
        return len(self.data) - self.pos

    def read_byte(self):
        if self.pos >= len(self.data):
            raise DecodeError("truncated_message", "unexpected end of data")
        b = self.data[self.pos]
        self.pos += 1
        return b

    def read_bytes(self, n):
        if self.pos + n > len(self.data):
            raise DecodeError("truncated_message",
                              f"need {n} bytes, have {self.remaining()}")
        result = self.data[self.pos:self.pos + n]
        self.pos += n
        return result

    def is_empty(self):
        return self.pos >= len(self.data)


# Maximum varint encoded lengths per type: ceil(type_bits / 7)
VARINT_MAX = {
    'u16': 3, 'i16': 3,
    'u32': 5, 'i32': 5,
    'u64': 10, 'i64': 10,
    'u128': 19, 'i128': 19,
    'usize': 10,  # 64-bit platform -> u64
    'disc': 5,    # enum discriminant is varint(u32)
}


def cobs_deframe(stream):
    """Split a byte stream on 0x00 sentinels into COBS-encoded frames."""
    frames = []
    current = bytearray()
    for b in stream:
        if b == 0x00:
            if len(current) > 0:
                frames.append(bytes(current))
                current = bytearray()
        else:
            current.append(b)
    if len(current) > 0:
        frames.append(bytes(current))
    return frames


def cobs_decode(data):
    """Decode a COBS-encoded frame (without sentinel bytes)."""
    output = bytearray()
    i = 0
    while i < len(data):
        code = data[i]
        i += 1
        if code == 0:
            raise DecodeError("cobs_error", "zero byte encountered in COBS data")
        if i + (code - 1) > len(data):
            raise DecodeError("cobs_error",
                              f"COBS code byte {code} exceeds remaining frame ({len(data) - i} bytes)")
        for _ in range(1, code):
            output.append(data[i])
            i += 1
        if code < 0xFF and i < len(data):
            output.append(0x00)
    return bytes(output)


def decode_varint_unsigned(reader, max_bytes):
    """Decode an unsigned varint with a maximum byte count limit."""
    result = 0
    shift = 0
    count = 0
    while True:
        if count >= max_bytes:
            raise DecodeError("varint_overflow",
                              f"varint exceeds maximum {max_bytes} bytes for type")
        b = reader.read_byte()
        count += 1
        result |= (b & 0x7F) << shift
        shift += 7
        if (b & 0x80) == 0:
            break
    return result


def zigzag_decode(value):
    """Decode a zigzag-encoded integer to its signed representation."""
    return (value >> 1) ^ -(value & 1)


def decode_type(reader, type_spec, schema):
    """Recursively decode a value according to its type specification and schema."""
    if isinstance(type_spec, str):
        # Primitive or named type
        if type_spec == 'u8':
            return reader.read_byte()
        elif type_spec == 'i8':
            b = reader.read_byte()
            return b if b < 128 else b - 256
        elif type_spec == 'u16':
            val = decode_varint_unsigned(reader, VARINT_MAX['u16'])
            if val > 0xFFFF:
                raise DecodeError("value_overflow", f"u16 value {val} exceeds 65535")
            return val
        elif type_spec == 'u32':
            val = decode_varint_unsigned(reader, VARINT_MAX['u32'])
            if val > 0xFFFFFFFF:
                raise DecodeError("value_overflow", f"u32 value {val} exceeds max")
            return val
        elif type_spec == 'u64':
            val = decode_varint_unsigned(reader, VARINT_MAX['u64'])
            if val > 0xFFFFFFFFFFFFFFFF:
                raise DecodeError("value_overflow", "u64 value exceeds max")
            return val
        elif type_spec == 'i16':
            raw = decode_varint_unsigned(reader, VARINT_MAX['i16'])
            if raw > 0xFFFF:
                raise DecodeError("value_overflow", "i16 zigzag value exceeds range")
            return zigzag_decode(raw)
        elif type_spec == 'i32':
            raw = decode_varint_unsigned(reader, VARINT_MAX['i32'])
            if raw > 0xFFFFFFFF:
                raise DecodeError("value_overflow", "i32 zigzag value exceeds range")
            return zigzag_decode(raw)
        elif type_spec == 'i64':
            raw = decode_varint_unsigned(reader, VARINT_MAX['i64'])
            if raw > 0xFFFFFFFFFFFFFFFF:
                raise DecodeError("value_overflow", "i64 zigzag value exceeds range")
            return zigzag_decode(raw)
        elif type_spec == 'f32':
            data = reader.read_bytes(4)
            return struct.unpack('<f', data)[0]
        elif type_spec == 'f64':
            data = reader.read_bytes(8)
            return struct.unpack('<d', data)[0]
        elif type_spec == 'bool':
            b = reader.read_byte()
            if b == 0x00:
                return False
            elif b == 0x01:
                return True
            else:
                raise DecodeError("invalid_bool",
                                  f"bool value 0x{b:02X} is not 0x00 or 0x01")
        elif type_spec == 'string':
            length = decode_varint_unsigned(reader, VARINT_MAX['usize'])
            data = reader.read_bytes(length)
            try:
                return data.decode('utf-8')
            except UnicodeDecodeError as e:
                raise DecodeError("invalid_utf8",
                                  f"string contains invalid UTF-8: {e}")
        elif type_spec in schema['types']:
            return decode_enum(reader, type_spec, schema)
        else:
            raise DecodeError("unknown_type", f"unknown type: {type_spec}")

    elif isinstance(type_spec, dict):
        if 'seq' in type_spec:
            elem_type = type_spec['seq']
            count = decode_varint_unsigned(reader, VARINT_MAX['usize'])
            return [decode_type(reader, elem_type, schema) for _ in range(count)]
        elif 'option' in type_spec:
            inner_type = type_spec['option']
            tag = reader.read_byte()
            if tag == 0x00:
                return None
            elif tag == 0x01:
                return decode_type(reader, inner_type, schema)
            else:
                raise DecodeError("invalid_option",
                                  f"option tag byte 0x{tag:02X} is not 0x00 or 0x01")
        else:
            raise DecodeError("unknown_type", f"unknown composite type: {type_spec}")
    else:
        raise DecodeError("unknown_type", f"unrecognized type spec: {type_spec}")


def decode_enum(reader, type_name, schema):
    """Decode a tagged union (enum) from the byte stream."""
    type_def = schema['types'][type_name]
    assert type_def['kind'] == 'enum', f"{type_name} is not an enum"

    # Discriminant is varint(u32)
    disc = decode_varint_unsigned(reader, VARINT_MAX['disc'])

    # Look up variant by discriminant
    variant = None
    for v in type_def['variants']:
        if v['discriminant'] == disc:
            variant = v
            break

    if variant is None:
        raise DecodeError("invalid_discriminant",
                          f"{type_name} has no variant with discriminant {disc}")

    # Decode fields in definition order (struct encoding)
    result = {"_variant": variant['name']}
    for field in variant.get('fields', []):
        result[field['name']] = decode_type(reader, field['type'], schema)

    return result


def decode_message(raw_bytes, schema):
    """Decode a single postcard message using the root type from schema."""
    reader = ByteReader(raw_bytes)
    return decode_enum(reader, schema['root_type'], schema)


def main():
    with open('/app/capture.bin', 'rb') as f:
        capture_data = f.read()

    schema = SCHEMA

    # COBS deframe
    cobs_frames = cobs_deframe(capture_data)

    messages = []
    valid_count = 0
    invalid_count = 0
    type_counts = {}

    for idx, frame in enumerate(cobs_frames):
        try:
            raw = cobs_decode(frame)
            decoded = decode_message(raw, schema)
            variant_name = decoded.get('_variant', 'Unknown')
            type_counts[variant_name] = type_counts.get(variant_name, 0) + 1
            valid_count += 1
            messages.append({
                'index': idx,
                'valid': True,
                'type': variant_name,
                'data': decoded,
            })
        except DecodeError as e:
            invalid_count += 1
            messages.append({
                'index': idx,
                'valid': False,
                'error_type': e.error_type,
                'error_detail': e.detail,
            })
        except Exception as e:
            invalid_count += 1
            messages.append({
                'index': idx,
                'valid': False,
                'error_type': 'decode_error',
                'error_detail': str(e),
            })

    report = {
        'total_messages': len(cobs_frames),
        'valid_count': valid_count,
        'invalid_count': invalid_count,
        'type_counts': type_counts,
        'messages': messages,
    }

    with open('/app/report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Decoded {len(cobs_frames)} frames: "
          f"{valid_count} valid, {invalid_count} invalid")


if __name__ == '__main__':
    main()
