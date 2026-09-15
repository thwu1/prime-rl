#!/usr/bin/env python3
"""
Postcard wire format codec with COBS framing.

Implements the Postcard v1.0 binary serialization wire format with
COBS (Consistent Overhead Byte Stuffing) framing for embedded
communication protocols.
"""

import struct
import math

USIZE_BITS = 32

PRIMITIVE_TYPES = {
    'bool', 'u8', 'i8', 'u16', 'u32', 'u64', 'u128',
    'i16', 'i32', 'i64', 'i128', 'f32', 'f64',
    'string', 'bytes', 'char', 'unit'
}


# ============================================================
# Varint
# ============================================================

def max_varint_len(type_bits):
    """Maximum encoded varint length in bytes for a given bit width."""
    return math.ceil(type_bits / 7)


def varint_encode(value, type_bits):
    """Encode an unsigned integer as a varint (LEB128-style)."""
    if value < 0:
        raise ValueError("varint_encode requires non-negative value")
    max_val = (1 << type_bits) - 1
    if value > max_val:
        raise ValueError(f"Value {value} exceeds {type_bits}-bit range")
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value > 0:
            byte |= 0x80
            result.append(byte)
        else:
            result.append(byte)
            break
    return bytes(result)


def varint_decode(data, type_bits):
    """Decode a varint, returning (value, bytes_consumed).

    Rejects encodings that exceed max_varint_len or the type's value range.
    """
    max_len = max_varint_len(type_bits)
    value = 0
    shift = 0
    for i in range(len(data)):
        if i >= max_len:
            raise ValueError(f"Varint exceeds max encoded length ({max_len}) for {type_bits}-bit type")
        byte = data[i]
        value |= (byte & 0x7F) << shift
        shift += 7
        if not (byte & 0x80):
            if value >= (1 << type_bits):
                raise ValueError(f"Decoded value {value} exceeds {type_bits}-bit range")
            return (value, i + 1)
    raise ValueError("Unterminated varint")


def is_canonical_varint(data, type_bits):
    """Check if a varint encoding is canonical.

    Canonical means re-encoding the decoded value produces identical bytes.
    """
    if isinstance(data, (list, tuple)):
        data = bytes(data)
    if len(data) == 0:
        return False
    if data[-1] & 0x80:
        return False
    for i in range(len(data) - 1):
        if not (data[i] & 0x80):
            return False
    try:
        value, consumed = varint_decode(data, type_bits)
    except ValueError:
        return False
    if consumed != len(data):
        return False
    canonical = varint_encode(value, type_bits)
    return canonical == data


# ============================================================
# Zigzag
# ============================================================

def zigzag_encode(value):
    """Encode a signed integer using zigzag encoding."""
    if value >= 0:
        return value * 2
    else:
        return (-value) * 2 - 1


def zigzag_decode(value):
    """Decode a zigzag-encoded unsigned integer back to signed."""
    if value & 1:
        return -(value >> 1) - 1
    else:
        return value >> 1


# ============================================================
# COBS
# ============================================================

def cobs_encode(data):
    """Encode data using COBS (Consistent Overhead Byte Stuffing).

    The output will not contain any 0x00 bytes. A 0xFF code byte
    indicates 254 data bytes follow with no implicit zero appended.
    """
    if isinstance(data, (list, tuple)):
        data = bytes(data)
    output = bytearray()
    idx = 0
    while True:
        code_idx = len(output)
        output.append(0)  # placeholder for code byte
        count = 1
        while idx < len(data) and data[idx] != 0 and count < 255:
            output.append(data[idx])
            idx += 1
            count += 1
        if count == 255:
            output[code_idx] = 0xFF
        else:
            output[code_idx] = count
            if idx < len(data) and data[idx] == 0:
                idx += 1
            else:
                break
    return bytes(output)


def cobs_decode(data):
    """Decode COBS-encoded data.

    Processes code bytes: each code byte N means read N-1 data bytes,
    then if N < 0xFF and more data remains, append a 0x00.
    """
    if isinstance(data, (list, tuple)):
        data = bytes(data)
    output = bytearray()
    idx = 0
    while idx < len(data):
        code = data[idx]
        idx += 1
        if code == 0:
            break
        for _ in range(code - 1):
            if idx >= len(data):
                raise ValueError("COBS decode: unexpected end of data")
            output.append(data[idx])
            idx += 1
        if code < 0xFF and idx < len(data):
            output.append(0x00)
    return bytes(output)


def frame_messages(messages):
    """COBS-encode each message and join with 0x00 sentinel delimiters."""
    output = bytearray()
    for msg in messages:
        encoded = cobs_encode(msg)
        output.extend(encoded)
        output.append(0x00)
    return bytes(output)


def unframe_messages(stream):
    """Split a COBS-framed stream on 0x00 sentinels and decode each frame."""
    messages = []
    current = bytearray()
    for byte in stream:
        if byte == 0x00:
            if len(current) > 0:
                decoded = cobs_decode(bytes(current))
                messages.append(decoded)
            current = bytearray()
        else:
            current.append(byte)
    if len(current) > 0:
        decoded = cobs_decode(bytes(current))
        messages.append(decoded)
    return messages


# ============================================================
# Schema-driven Serialization
# ============================================================

def serialize(schema, type_name, data):
    """Serialize data according to a schema type definition."""
    buf = bytearray()
    _serialize_value(schema, type_name, data, buf)
    return bytes(buf)


def deserialize(schema, type_name, data):
    """Deserialize data according to a schema type definition.

    Returns (value, bytes_consumed).
    """
    if isinstance(data, (list, tuple)):
        data = bytes(data)
    value, offset = _deserialize_value(schema, type_name, data, 0)
    return (value, offset)


# --- Internal serialization ---

def _serialize_value(schema, type_ref, data, buf):
    """Serialize a value according to its type reference."""
    if isinstance(type_ref, str):
        if type_ref in PRIMITIVE_TYPES:
            _serialize_primitive(type_ref, data, buf)
        else:
            type_def = schema['types'][type_ref]
            _serialize_type_def(schema, type_def, data, buf)
    elif isinstance(type_ref, dict):
        if 'seq' in type_ref:
            elem_type = type_ref['seq']
            buf.extend(varint_encode(len(data), USIZE_BITS))
            for item in data:
                _serialize_value(schema, elem_type, item, buf)
        elif 'option' in type_ref:
            inner_type = type_ref['option']
            if data is None:
                buf.append(0x00)
            else:
                buf.append(0x01)
                _serialize_value(schema, inner_type, data, buf)
        elif 'map' in type_ref:
            key_type, val_type = type_ref['map']
            buf.extend(varint_encode(len(data), USIZE_BITS))
            for pair in data:
                _serialize_value(schema, key_type, pair[0], buf)
                _serialize_value(schema, val_type, pair[1], buf)


def _serialize_primitive(ptype, data, buf):
    """Serialize a primitive Serde data model type."""
    if ptype == 'bool':
        buf.append(0x01 if data else 0x00)
    elif ptype == 'u8':
        buf.append(data & 0xFF)
    elif ptype == 'i8':
        buf.extend(struct.pack('b', data))
    elif ptype in ('u16', 'u32', 'u64', 'u128'):
        bits = int(ptype[1:])
        buf.extend(varint_encode(data, bits))
    elif ptype in ('i16', 'i32', 'i64', 'i128'):
        bits = int(ptype[1:])
        unsigned = zigzag_encode(data)
        buf.extend(varint_encode(unsigned, bits))
    elif ptype == 'f32':
        buf.extend(struct.pack('<f', data))
    elif ptype == 'f64':
        buf.extend(struct.pack('<d', data))
    elif ptype == 'string':
        encoded = data.encode('utf-8')
        buf.extend(varint_encode(len(encoded), USIZE_BITS))
        buf.extend(encoded)
    elif ptype == 'bytes':
        raw = data if isinstance(data, (bytes, bytearray)) else bytes(data)
        buf.extend(varint_encode(len(raw), USIZE_BITS))
        buf.extend(raw)
    elif ptype == 'char':
        encoded = data.encode('utf-8')
        buf.extend(varint_encode(len(encoded), USIZE_BITS))
        buf.extend(encoded)
    elif ptype == 'unit':
        pass


def _serialize_type_def(schema, type_def, data, buf):
    """Serialize data according to a named type definition."""
    kind = type_def['kind']
    if kind == 'struct':
        for field in type_def['fields']:
            _serialize_value(schema, field['type'], data[field['name']], buf)
    elif kind == 'enum':
        _serialize_enum(schema, type_def, data, buf)
    elif kind == 'tuple_struct':
        for i, elem_type in enumerate(type_def['elements']):
            _serialize_value(schema, elem_type, data[i], buf)


def _serialize_enum(schema, type_def, data, buf):
    """Serialize an enum value with varint(u32) discriminant."""
    variants = type_def['variants']
    if isinstance(data, str):
        for i, v in enumerate(variants):
            if v['name'] == data:
                buf.extend(varint_encode(i, 32))
                return
        raise ValueError(f"Unknown unit variant: {data}")
    elif isinstance(data, dict):
        variant_name = next(iter(data))
        variant_data = data[variant_name]
        for i, v in enumerate(variants):
            if v['name'] == variant_name:
                buf.extend(varint_encode(i, 32))
                vspec = v.get('data')
                if vspec is None:
                    return
                vkind = vspec['kind']
                if vkind == 'newtype':
                    _serialize_value(schema, vspec['type'], variant_data, buf)
                elif vkind == 'tuple':
                    for j, elem_type in enumerate(vspec['elements']):
                        _serialize_value(schema, elem_type, variant_data[j], buf)
                elif vkind == 'struct':
                    for field in vspec['fields']:
                        _serialize_value(schema, field['type'],
                                         variant_data[field['name']], buf)
                return
        raise ValueError(f"Unknown variant: {variant_name}")


# --- Internal deserialization ---

def _deserialize_value(schema, type_ref, data, offset):
    """Deserialize a value, returning (value, new_offset)."""
    if isinstance(type_ref, str):
        if type_ref in PRIMITIVE_TYPES:
            return _deserialize_primitive(type_ref, data, offset)
        else:
            type_def = schema['types'][type_ref]
            return _deserialize_type_def(schema, type_def, data, offset)
    elif isinstance(type_ref, dict):
        if 'seq' in type_ref:
            return _deserialize_seq(schema, type_ref['seq'], data, offset)
        elif 'option' in type_ref:
            return _deserialize_option(schema, type_ref['option'], data, offset)
        elif 'map' in type_ref:
            return _deserialize_map(schema, type_ref['map'], data, offset)
    raise ValueError(f"Unknown type reference: {type_ref}")


def _deserialize_primitive(ptype, data, offset):
    """Deserialize a primitive type."""
    if ptype == 'bool':
        val = data[offset]
        if val == 0:
            return (False, offset + 1)
        elif val == 1:
            return (True, offset + 1)
        else:
            raise ValueError(f"Invalid bool value: {val}")
    elif ptype == 'u8':
        return (data[offset], offset + 1)
    elif ptype == 'i8':
        return (struct.unpack_from('b', data, offset)[0], offset + 1)
    elif ptype in ('u16', 'u32', 'u64', 'u128'):
        bits = int(ptype[1:])
        val, consumed = varint_decode(data[offset:], bits)
        return (val, offset + consumed)
    elif ptype in ('i16', 'i32', 'i64', 'i128'):
        bits = int(ptype[1:])
        unsigned, consumed = varint_decode(data[offset:], bits)
        return (zigzag_decode(unsigned), offset + consumed)
    elif ptype == 'f32':
        val = struct.unpack_from('<f', data, offset)[0]
        return (val, offset + 4)
    elif ptype == 'f64':
        val = struct.unpack_from('<d', data, offset)[0]
        return (val, offset + 8)
    elif ptype == 'string':
        length, consumed = varint_decode(data[offset:], USIZE_BITS)
        offset += consumed
        val = data[offset:offset + length].decode('utf-8')
        return (val, offset + length)
    elif ptype == 'bytes':
        length, consumed = varint_decode(data[offset:], USIZE_BITS)
        offset += consumed
        val = bytes(data[offset:offset + length])
        return (val, offset + length)
    elif ptype == 'char':
        length, consumed = varint_decode(data[offset:], USIZE_BITS)
        offset += consumed
        val = data[offset:offset + length].decode('utf-8')
        return (val, offset + length)
    elif ptype == 'unit':
        return (None, offset)
    raise ValueError(f"Unknown primitive type: {ptype}")


def _deserialize_seq(schema, elem_type, data, offset):
    """Deserialize a sequence (variable-length array)."""
    length, consumed = varint_decode(data[offset:], USIZE_BITS)
    offset += consumed
    result = []
    for _ in range(length):
        val, offset = _deserialize_value(schema, elem_type, data, offset)
        result.append(val)
    return (result, offset)


def _deserialize_option(schema, inner_type, data, offset):
    """Deserialize an option (None or Some)."""
    tag = data[offset]
    offset += 1
    if tag == 0:
        return (None, offset)
    elif tag == 1:
        val, offset = _deserialize_value(schema, inner_type, data, offset)
        return (val, offset)
    else:
        raise ValueError(f"Invalid option tag: {tag}")


def _deserialize_map(schema, type_pair, data, offset):
    """Deserialize a map as a list of [key, value] pairs."""
    key_type, val_type = type_pair
    length, consumed = varint_decode(data[offset:], USIZE_BITS)
    offset += consumed
    result = []
    for _ in range(length):
        key, offset = _deserialize_value(schema, key_type, data, offset)
        val, offset = _deserialize_value(schema, val_type, data, offset)
        result.append([key, val])
    return (result, offset)


def _deserialize_type_def(schema, type_def, data, offset):
    """Deserialize according to a named type definition."""
    kind = type_def['kind']
    if kind == 'struct':
        result = {}
        for field in type_def['fields']:
            val, offset = _deserialize_value(schema, field['type'], data, offset)
            result[field['name']] = val
        return (result, offset)
    elif kind == 'enum':
        return _deserialize_enum(schema, type_def, data, offset)
    elif kind == 'tuple_struct':
        result = []
        for elem_type in type_def['elements']:
            val, offset = _deserialize_value(schema, elem_type, data, offset)
            result.append(val)
        return (result, offset)
    raise ValueError(f"Unknown type kind: {kind}")


def _deserialize_enum(schema, type_def, data, offset):
    """Deserialize an enum with varint(u32) discriminant."""
    disc, consumed = varint_decode(data[offset:], 32)
    offset += consumed
    variants = type_def['variants']
    if disc >= len(variants):
        raise ValueError(f"Invalid enum discriminant: {disc}")
    variant = variants[disc]
    name = variant['name']
    vspec = variant.get('data')
    if vspec is None:
        return (name, offset)
    vkind = vspec['kind']
    if vkind == 'newtype':
        val, offset = _deserialize_value(schema, vspec['type'], data, offset)
        return ({name: val}, offset)
    elif vkind == 'tuple':
        vals = []
        for elem_type in vspec['elements']:
            val, offset = _deserialize_value(schema, elem_type, data, offset)
            vals.append(val)
        return ({name: vals}, offset)
    elif vkind == 'struct':
        result = {}
        for field in vspec['fields']:
            val, offset = _deserialize_value(schema, field['type'], data, offset)
            result[field['name']] = val
        return ({name: result}, offset)
    raise ValueError(f"Unknown variant kind: {vkind}")
