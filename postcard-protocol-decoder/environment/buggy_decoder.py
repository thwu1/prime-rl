#!/usr/bin/env python3
"""
Decoder for COBS-framed postcard-rpc protocol messages.
Parses binary capture files using protocol schema.
"""

import struct
import json
from pathlib import Path


def cobs_decode(encoded):
    """Decode COBS-encoded bytes (without trailing 0x00 delimiter)."""
    output = bytearray()
    idx = 0
    while idx < len(encoded):
        code = encoded[idx]
        idx += 1
        if code == 0:
            raise ValueError("Zero byte in COBS data")
        for _ in range(code - 1):
            if idx >= len(encoded):
                raise ValueError("COBS truncated")
            output.append(encoded[idx])
            idx += 1
        if code < 0xFF and idx < len(encoded):
            output.append(0)
    return bytes(output)


def extract_cobs_frames(data):
    """Split binary data into COBS frames using 0x00 delimiter."""
    frames = []
    current = bytearray()
    for byte in data:
        if byte == 0:
            if current:
                frames.append(bytes(current))
            current = bytearray()
        else:
            current.append(byte)
    if current:
        frames.append(bytes(current))
    return frames


class PostcardDecoder:
    """Decode postcard wire format binary data."""

    def __init__(self, data):
        self.data = data
        self.pos = 0

    def remaining(self):
        return len(self.data) - self.pos

    def read_byte(self):
        if self.pos >= len(self.data):
            raise ValueError(f"Read past end at position {self.pos}")
        b = self.data[self.pos]
        self.pos += 1
        return b

    def read_bytes(self, n):
        if self.pos + n > len(self.data):
            raise ValueError(
                f"Cannot read {n} bytes at position {self.pos}, "
                f"only {self.remaining()} remain"
            )
        result = self.data[self.pos:self.pos + n]
        self.pos += n
        return result

    def read_varint_unsigned(self):
        """Read unsigned LEB128 varint."""
        value = 0
        shift = 0
        while True:
            byte = self.read_byte()
            value |= (byte & 0x7F) << shift
            if not (byte & 0x80):
                break
            shift += 7
            if shift > 70:
                raise ValueError("Varint too long")
        return value

    def read_varint_signed(self):
        """Read zigzag-encoded signed varint.

        Zigzag maps: 0->0, -1->1, 1->2, -2->3, 2->4, ...
        Decode: signed = (unsigned >> 1) XOR (unsigned & 1)
        """
        zigzag = self.read_varint_unsigned()
        return (zigzag >> 1) ^ (zigzag & 1)

    def decode_type(self, type_spec):
        if isinstance(type_spec, str):
            return self._decode_primitive(type_spec)
        elif isinstance(type_spec, dict):
            return self._decode_complex(type_spec)
        raise ValueError(f"Unknown type spec: {type_spec}")

    def _decode_primitive(self, type_name):
        if type_name == "bool":
            b = self.read_byte()
            if b == 0x00:
                return False
            elif b == 0x01:
                return True
            else:
                raise ValueError(f"Invalid bool: 0x{b:02x}")
        elif type_name == "u8":
            return self.read_byte()
        elif type_name == "i8":
            return struct.unpack('b', bytes([self.read_byte()]))[0]
        elif type_name == "u16":
            return self.read_varint_unsigned()
        elif type_name == "i16":
            return self.read_varint_signed()
        elif type_name == "u32":
            return self.read_varint_unsigned()
        elif type_name == "i32":
            return self.read_varint_signed()
        elif type_name == "u64":
            return self.read_varint_unsigned()
        elif type_name == "i64":
            return self.read_varint_signed()
        elif type_name == "f32":
            return struct.unpack('>f', self.read_bytes(4))[0]
        elif type_name == "f64":
            return struct.unpack('>d', self.read_bytes(8))[0]
        elif type_name == "string":
            length = self.read_varint_unsigned()
            return self.read_bytes(length).decode('utf-8')
        elif type_name == "bytes":
            length = self.read_varint_unsigned()
            return list(self.read_bytes(length))
        else:
            raise ValueError(f"Unknown primitive: {type_name}")

    def _decode_complex(self, type_spec):
        if "option" in type_spec:
            flag = self.read_byte()
            if flag == 0x00:
                return None
            elif flag == 0x01:
                return self.decode_type(type_spec["option"])
            else:
                raise ValueError(f"Invalid option flag: 0x{flag:02x}")

        elif "seq" in type_spec:
            count = self.read_varint_unsigned()
            return [self.decode_type(type_spec["seq"]) for _ in range(count)]

        elif "tuple" in type_spec:
            count = self.read_varint_unsigned()
            types = type_spec["tuple"]
            result = []
            for i in range(count):
                result.append(self.decode_type(types[i % len(types)]))
            return result

        elif "map" in type_spec:
            key_type, val_type = type_spec["map"]
            count = self.read_varint_unsigned()
            result = {}
            for _ in range(count):
                k = self.decode_type(key_type)
                v = self.decode_type(val_type)
                result[k] = v
            return result

        elif "unit_variant" in type_spec:
            discriminant = self.read_varint_unsigned()
            variants = type_spec["unit_variant"]
            if discriminant < len(variants):
                return variants[discriminant]
            else:
                raise ValueError(f"Unknown unit_variant: {discriminant}")

        elif "enum" in type_spec:
            discriminant = self.read_varint_unsigned()
            variants = type_spec["enum"]
            if discriminant >= len(variants):
                raise ValueError(f"Unknown enum discriminant: {discriminant}")
            variant = variants[discriminant]
            name = variant["name"]
            data_spec = variant.get("data")

            if data_spec is None:
                return name

            elif isinstance(data_spec, dict) and "struct" in data_spec:
                fields = []
                for field_def in data_spec["struct"]:
                    fields.append(self.decode_type(field_def["type"]))
                return {name: fields}
            else:
                return {name: self.decode_type(data_spec)}

        else:
            raise ValueError(f"Unknown complex type: {type_spec}")


def decode_frame(raw_frame, protocol):
    """Decode a single raw (COBS-decoded) postcard-rpc frame."""
    decoder = PostcardDecoder(raw_frame)
    key_bytes = decoder.read_bytes(8)
    key_hex = key_bytes.hex()
    seq_no = decoder.read_varint_unsigned()

    messages = protocol["messages"]
    if key_hex not in messages:
        return None

    msg_def = messages[key_hex]
    body = {}
    for field_def in msg_def["fields"]:
        body[field_def["name"]] = decoder.decode_type(field_def["type"])

    return {
        "session": None,
        "seq_no": seq_no,
        "message_type": msg_def["name"],
        "body": body,
    }


def main():
    with open('/app/protocol.json') as f:
        protocol = json.load(f)

    results = []
    capture_dir = Path('/app/captures')

    for bin_file in sorted(capture_dir.glob('*.bin')):
        session_name = bin_file.stem
        raw_data = bin_file.read_bytes()
        encoded_frames = extract_cobs_frames(raw_data)
        for encoded_frame in encoded_frames:
            try:
                decoded_data = cobs_decode(encoded_frame)
                msg = decode_frame(decoded_data, protocol)
                if msg is not None:
                    msg["session"] = session_name
                    results.append(msg)
            except Exception as e:
                print(f"Warning: failed to decode frame in {session_name}: {e}")

    with open('/app/output.json', 'w') as f:
        json.dump(results, f, indent=2)
    print(f"Decoded {len(results)} messages to /app/output.json")


if __name__ == '__main__':
    main()
