#!/usr/bin/env python3
"""
Empirically test wire-level forward compatibility of proposed schema migrations.

For each migration, encodes test data using the v1 schema, then attempts to
decode with the v2 (post-migration) schema. A migration is compatible only if
all test values decode correctly with no errors and no trailing bytes.
"""

import json
import struct
import copy
import sys
import os

sys.path.insert(0, '/app')
from decoder import PostcardDecoder


# ---------------------------------------------------------------------------
# Encoder (inverse of decoder)
# ---------------------------------------------------------------------------

def encode_varint_unsigned(value):
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def zigzag_encode(value):
    return value * 2 if value >= 0 else (-value) * 2 - 1


def encode_type(value, type_spec):
    if isinstance(type_spec, str):
        return _encode_primitive(value, type_spec)
    elif isinstance(type_spec, dict):
        return _encode_complex(value, type_spec)
    raise ValueError(f"Unknown type spec: {type_spec}")


def _encode_primitive(value, type_name):
    if type_name == "bool":
        return bytes([0x01 if value else 0x00])
    elif type_name == "u8":
        return bytes([int(value) & 0xFF])
    elif type_name == "i8":
        return struct.pack('b', int(value))
    elif type_name in ("u16", "u32", "u64"):
        return encode_varint_unsigned(int(value))
    elif type_name in ("i16", "i32", "i64"):
        return encode_varint_unsigned(zigzag_encode(int(value)))
    elif type_name == "f32":
        return struct.pack('<f', float(value))
    elif type_name == "f64":
        return struct.pack('<d', float(value))
    elif type_name == "string":
        b = str(value).encode('utf-8')
        return encode_varint_unsigned(len(b)) + b
    raise ValueError(f"Unknown primitive: {type_name}")


def _encode_complex(value, type_spec):
    if "option" in type_spec:
        if value is None:
            return bytes([0x00])
        return bytes([0x01]) + encode_type(value, type_spec["option"])

    elif "seq" in type_spec:
        result = bytearray(encode_varint_unsigned(len(value)))
        for item in value:
            result += encode_type(item, type_spec["seq"])
        return bytes(result)

    elif "tuple" in type_spec:
        result = bytearray()
        for item, t in zip(value, type_spec["tuple"]):
            result += encode_type(item, t)
        return bytes(result)

    elif "map" in type_spec:
        key_type, val_type = type_spec["map"]
        result = bytearray(encode_varint_unsigned(len(value)))
        for k, v in value.items():
            result += encode_type(k, key_type)
            result += encode_type(v, val_type)
        return bytes(result)

    elif "unit_variant" in type_spec:
        idx = type_spec["unit_variant"].index(value)
        return encode_varint_unsigned(idx)

    elif "enum" in type_spec:
        variants = type_spec["enum"]
        if isinstance(value, str):
            for i, v in enumerate(variants):
                if v["name"] == value:
                    return encode_varint_unsigned(i)
        elif isinstance(value, dict):
            name = list(value.keys())[0]
            data = value[name]
            for i, v in enumerate(variants):
                if v["name"] == name:
                    result = bytearray(encode_varint_unsigned(i))
                    data_spec = v.get("data")
                    if isinstance(data_spec, dict) and "struct" in data_spec:
                        for field_def in data_spec["struct"]:
                            result += encode_type(
                                data[field_def["name"]], field_def["type"]
                            )
                    else:
                        result += encode_type(data, data_spec)
                    return bytes(result)
        raise ValueError(f"Cannot encode enum value: {value}")

    raise ValueError(f"Unknown complex type: {type_spec}")


# ---------------------------------------------------------------------------
# Struct-level encode / decode
# ---------------------------------------------------------------------------

def encode_struct(values, fields):
    result = bytearray()
    for field in fields:
        result += encode_type(values[field["name"]], field["type"])
    return bytes(result)


def try_decode_struct(data, fields):
    """Try to decode data using field definitions.
    Returns (True, decoded_dict) or (False, error_string).
    """
    try:
        decoder = PostcardDecoder(data)
        result = {}
        for field in fields:
            result[field["name"]] = decoder.decode_type(field["type"])
        if decoder.remaining() > 0:
            return False, "trailing bytes after struct"
        return True, result
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Migration application
# ---------------------------------------------------------------------------

def apply_migration(fields, migration):
    new_fields = copy.deepcopy(fields)

    if "action" in migration and migration["action"] == "append_field":
        new_fields.append(migration["new_field"])

    elif "v1_variant_order" in migration and "v2_variant_order" in migration:
        field_name = migration["field"]
        for f in new_fields:
            if f["name"] == field_name:
                old_type = f["type"]
                if "enum" in old_type:
                    old_variants = old_type["enum"]
                    new_order = migration["v2_variant_order"]
                    new_variants = []
                    for vname in new_order:
                        for ov in old_variants:
                            if ov["name"] == vname:
                                new_variants.append(copy.deepcopy(ov))
                                break
                    f["type"] = {"enum": new_variants}
                elif "unit_variant" in old_type:
                    f["type"] = {"unit_variant": migration["v2_variant_order"]}

    elif "v1_field" in migration and "v2_field" in migration:
        field_name = migration["v1_field"]["name"]
        for f in new_fields:
            if f["name"] == field_name:
                f["type"] = migration["v2_field"]["type"]

    return new_fields


def get_key_for_type(type_name, schema):
    for key, msg in schema["messages"].items():
        if msg["name"] == type_name:
            return key
    return None


# ---------------------------------------------------------------------------
# Test data generators
# ---------------------------------------------------------------------------

def generate_test_values(msg_name):
    if msg_name == "SensorReading":
        return [
            {"sensor_id": 1023, "temperature": -15,
             "humidity": 65.5, "label": "temp_a"},
            {"sensor_id": 0, "temperature": 0,
             "humidity": 0.0, "label": ""},
        ]
    elif msg_name == "MotorCommand":
        return [
            {"motor_idx": 3, "speed": -500,
             "direction": "Reverse", "duration_ms": 2000},
            {"motor_idx": 0, "speed": 0,
             "direction": "Forward", "duration_ms": None},
            {"motor_idx": 1, "speed": 100,
             "direction": "Forward", "duration_ms": 5000},
        ]
    elif msg_name == "DeviceStatus":
        return [
            {"uptime_secs": 86400, "errors": [1, 257],
             "firmware_version": [1, 4, 2],
             "config": {"gain": 100, "offset": -5}},
            {"uptime_secs": 0, "errors": [],
             "firmware_version": [0, 0, 1], "config": {}},
        ]
    elif msg_name == "Alert":
        return [
            {"timestamp": 5000,
             "severity": {"Warning": "temperature rising"},
             "acknowledged": False},
            {"timestamp": 5002,
             "severity": {"Critical": {"code": 1001,
                                       "detail": "motor stall",
                                       "recoverable": False}},
             "acknowledged": False},
            {"timestamp": 6000, "severity": "Info",
             "acknowledged": True},
        ]
    return []


def values_match(v1, v2):
    """Compare decoded values, handling float precision and structural equivalence.

    Handles the case where a map decoded as seq-of-tuples produces a list
    of [key, value] pairs instead of a dict -- these are semantically equivalent.
    """
    if isinstance(v1, float) and isinstance(v2, float):
        return abs(v1 - v2) < 1e-6
    elif isinstance(v1, dict) and isinstance(v2, list):
        # map → seq<tuple> produces list of [key, value] pairs
        try:
            v2_as_dict = {}
            for pair in v2:
                if not isinstance(pair, list) or len(pair) != 2:
                    return False
                v2_as_dict[pair[0]] = pair[1]
            return values_match(v1, v2_as_dict)
        except (ValueError, TypeError):
            return False
    elif isinstance(v1, dict) and isinstance(v2, dict):
        if set(v1.keys()) != set(v2.keys()):
            return False
        return all(values_match(v1[k], v2[k]) for k in v1)
    elif isinstance(v1, list) and isinstance(v2, list):
        if len(v1) != len(v2):
            return False
        return all(values_match(a, b) for a, b in zip(v1, v2))
    else:
        return v1 == v2


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    with open('/app/schema.json') as f:
        schema = json.load(f)
    with open('/app/migrations.json') as f:
        migrations = json.load(f)

    report = []

    for migration in migrations:
        mid = migration["migration_id"]
        msg_type = migration["message_type"]
        key = get_key_for_type(msg_type, schema)
        v1_fields = schema["messages"][key]["fields"]
        v2_fields = apply_migration(v1_fields, migration)

        test_values = generate_test_values(msg_type)
        compatible = True

        for test_val in test_values:
            # Encode with v1 schema
            try:
                v1_encoded = encode_struct(test_val, v1_fields)
            except Exception as e:
                print(f"  {mid}: v1 encode failed for {test_val}: {e}")
                continue

            # Decode with v2 schema
            success, decoded = try_decode_struct(v1_encoded, v2_fields)
            if not success:
                compatible = False
                print(f"  {mid}: INCOMPATIBLE — decode failed: {decoded}")
                break

            # Compare decoded values against original test values
            for v1_field in v1_fields:
                fname = v1_field["name"]
                if fname in test_val and fname in decoded:
                    if not values_match(test_val[fname], decoded[fname]):
                        compatible = False
                        print(f"  {mid}: INCOMPATIBLE — field '{fname}' "
                              f"value mismatch: {test_val[fname]} vs "
                              f"{decoded[fname]}")
                        break
            if not compatible:
                break

        report.append({"migration_id": mid, "compatible": compatible})
        status = "compatible" if compatible else "INCOMPATIBLE"
        print(f"{mid}: {status}")

    with open('/app/compatibility_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    print(f"\nWrote compatibility report to /app/compatibility_report.json")


if __name__ == '__main__':
    main()
