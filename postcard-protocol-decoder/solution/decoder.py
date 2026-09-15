#!/usr/bin/env python3
"""
Complete postcard wire format decoder with CRC-8 validation.
Implements COBS deframing, CRC-8 integrity checks, LEB128 varints,
zigzag signed encoding, IEEE 754 floats, and all serde data model types.
"""

import struct
import json
from pathlib import Path


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
        """Read zigzag-encoded signed varint."""
        z = self.read_varint_unsigned()
        return (z >> 1) ^ -(z & 1)

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
        elif type_name in ("u16", "u32", "u64"):
            return self.read_varint_unsigned()
        elif type_name in ("i16", "i32", "i64"):
            return self.read_varint_signed()
        elif type_name == "f32":
            return struct.unpack('<f', self.read_bytes(4))[0]
        elif type_name == "f64":
            return struct.unpack('<d', self.read_bytes(8))[0]
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
            types = type_spec["tuple"]
            return [self.decode_type(t) for t in types]

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
                fields = {}
                for field_def in data_spec["struct"]:
                    fields[field_def["name"]] = self.decode_type(field_def["type"])
                return {name: fields}
            else:
                return {name: self.decode_type(data_spec)}

        else:
            raise ValueError(f"Unknown complex type: {type_spec}")


def decode_frame(raw_frame, protocol):
    """Decode a single raw (COBS-decoded, CRC-stripped) postcard-rpc frame."""
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
    with open('/app/schema.json') as f:
        protocol = json.load(f)

    decoded_messages = []
    frame_analysis = []
    capture_dir = Path('/app/captures')

    for bin_file in sorted(capture_dir.glob('*.bin')):
        session_name = bin_file.stem
        raw_data = bin_file.read_bytes()
        encoded_frames = extract_cobs_frames(raw_data)

        for frame_idx, encoded_frame in enumerate(encoded_frames):
            try:
                decoded_data = cobs_decode(encoded_frame)
            except Exception as e:
                frame_analysis.append({
                    "session": session_name,
                    "frame_index": frame_idx,
                    "crc_valid": False,
                    "key_hex": "unknown",
                })
                continue

            if len(decoded_data) < 9:
                frame_analysis.append({
                    "session": session_name,
                    "frame_index": frame_idx,
                    "crc_valid": False,
                    "key_hex": "unknown",
                })
                continue

            # Last byte is CRC, rest is payload
            payload = decoded_data[:-1]
            stored_crc = decoded_data[-1]
            computed_crc = crc8(payload)
            crc_valid = (stored_crc == computed_crc)

            # Extract key hex (first 8 bytes of payload)
            key_hex = payload[:8].hex()

            frame_analysis.append({
                "session": session_name,
                "frame_index": frame_idx,
                "crc_valid": crc_valid,
                "key_hex": key_hex,
            })

            if not crc_valid:
                continue

            # Decode valid frame
            try:
                msg = decode_frame(payload, protocol)
                if msg is not None:
                    msg["session"] = session_name
                    decoded_messages.append(msg)
            except Exception as e:
                print(f"Warning: failed to decode frame in {session_name}: {e}")

    # Write frame analysis
    with open('/app/frame_analysis.json', 'w') as f:
        json.dump(frame_analysis, f, indent=2)
    print(f"Wrote frame analysis: {len(frame_analysis)} frames")

    # Write decoded messages
    with open('/app/decoded_messages.json', 'w') as f:
        json.dump(decoded_messages, f, indent=2)
    print(f"Decoded {len(decoded_messages)} messages to /app/decoded_messages.json")


if __name__ == '__main__':
    main()
