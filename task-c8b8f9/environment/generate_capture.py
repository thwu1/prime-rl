#!/usr/bin/env python3
"""
Generate capture.bin containing COBS-framed postcard-serialized messages.
Usage: python3 generate_capture.py <output_path>
"""

import struct
import sys
import os


def cobs_encode(data):
    """COBS encode data bytes (without sentinel)."""
    data = bytes(data)
    if len(data) == 0:
        return bytes([0x01])
    output = bytearray()
    code_idx = 0
    output.append(0)  # placeholder for first code byte
    code = 1
    for byte in data:
        if byte == 0:
            output[code_idx] = code
            code_idx = len(output)
            output.append(0)  # placeholder
            code = 1
        else:
            output.append(byte)
            code += 1
            if code == 0xFF:
                output[code_idx] = code
                code_idx = len(output)
                output.append(0)  # placeholder
                code = 1
    output[code_idx] = code
    return bytes(output)


def encode_varint_u(value):
    """Encode unsigned integer as postcard varint (LEB128-style)."""
    if value == 0:
        return bytes([0x00])
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def zigzag_encode(value):
    """Zigzag encode a signed integer."""
    if value >= 0:
        return value << 1
    else:
        return ((-value) << 1) - 1


def encode_varint_i(value):
    """Encode signed integer as zigzag + varint."""
    return encode_varint_u(zigzag_encode(value))


def encode_f32(value):
    """Encode f32 as 4 little-endian bytes."""
    return struct.pack('<f', value)


def encode_string(s):
    """Encode string as varint(len) + UTF-8 bytes."""
    encoded = s.encode('utf-8')
    return encode_varint_u(len(encoded)) + encoded


def build_messages():
    """Build all test messages (both valid and invalid)."""
    messages = []

    # --- Valid messages (indices 0-17) ---

    # 0: SensorReading(sensor_id=42, timestamp=1000000, values=[23.5, 24.125], status=None)
    msg = bytearray()
    msg += encode_varint_u(0)        # Message::SensorReading
    msg += encode_varint_u(42)       # sensor_id: u16
    msg += encode_varint_u(1000000)  # timestamp: u32
    msg += encode_varint_u(2)        # values: seq len
    msg += encode_f32(23.5)
    msg += encode_f32(24.125)
    msg += bytes([0x00])             # status: None
    messages.append(bytes(msg))

    # 1: SensorReading(sensor_id=7, timestamp=2000000, values=[18.25], status=Some(Ok))
    msg = bytearray()
    msg += encode_varint_u(0)
    msg += encode_varint_u(7)
    msg += encode_varint_u(2000000)
    msg += encode_varint_u(1)        # values len = 1
    msg += encode_f32(18.25)
    msg += bytes([0x01])             # status: Some
    msg += encode_varint_u(0)        # StatusCode::Ok
    messages.append(bytes(msg))

    # 2: ConfigUpdate(param_id=100, value=Int(-15))
    msg = bytearray()
    msg += encode_varint_u(1)        # Message::ConfigUpdate
    msg += encode_varint_u(100)      # param_id: u16
    msg += encode_varint_u(0)        # ConfigValue::Int
    msg += encode_varint_i(-15)      # value: i32
    messages.append(bytes(msg))

    # 3: ConfigUpdate(param_id=200, value=Float(3.140625))
    msg = bytearray()
    msg += encode_varint_u(1)
    msg += encode_varint_u(200)
    msg += encode_varint_u(1)        # ConfigValue::Float
    msg += encode_f32(3.140625)
    messages.append(bytes(msg))

    # 4: ConfigUpdate(param_id=300, value=Str("hello"))
    msg = bytearray()
    msg += encode_varint_u(1)
    msg += encode_varint_u(300)
    msg += encode_varint_u(2)        # ConfigValue::Str
    msg += encode_string("hello")
    messages.append(bytes(msg))

    # 5: ConfigUpdate(param_id=400, value=Bool(true))
    msg = bytearray()
    msg += encode_varint_u(1)
    msg += encode_varint_u(400)
    msg += encode_varint_u(3)        # ConfigValue::Bool
    msg += bytes([0x01])             # true
    messages.append(bytes(msg))

    # 6: Heartbeat(uptime_ms=86400000, free_mem=65536)
    msg = bytearray()
    msg += encode_varint_u(2)        # Message::Heartbeat
    msg += encode_varint_u(86400000) # uptime_ms: u64
    msg += encode_varint_u(65536)    # free_mem: u32
    messages.append(bytes(msg))

    # 7: Heartbeat(uptime_ms=172800000, free_mem=32768)
    msg = bytearray()
    msg += encode_varint_u(2)
    msg += encode_varint_u(172800000)
    msg += encode_varint_u(32768)
    messages.append(bytes(msg))

    # 8: Alert(level=Info, source="temp", code=100)
    msg = bytearray()
    msg += encode_varint_u(3)        # Message::Alert
    msg += encode_varint_u(0)        # AlertLevel::Info
    msg += encode_string("temp")
    msg += encode_varint_u(100)
    messages.append(bytes(msg))

    # 9: Alert(level=Critical, source="pressure", code=500)
    msg = bytearray()
    msg += encode_varint_u(3)
    msg += encode_varint_u(2)        # AlertLevel::Critical
    msg += encode_string("pressure")
    msg += encode_varint_u(500)
    messages.append(bytes(msg))

    # 10: SensorReading(sensor_id=1, timestamp=0, values=[], status=Some(Warning(5)))
    msg = bytearray()
    msg += encode_varint_u(0)
    msg += encode_varint_u(1)
    msg += encode_varint_u(0)        # timestamp = 0
    msg += encode_varint_u(0)        # values: empty seq
    msg += bytes([0x01])             # status: Some
    msg += encode_varint_u(1)        # StatusCode::Warning
    msg += bytes([0x05])             # warning code: u8 = 5
    messages.append(bytes(msg))

    # 11: SensorReading(sensor_id=255, timestamp=4294967295, values=[0.0, -1.0, 100.5],
    #                    status=Some(Error(1024)))
    msg = bytearray()
    msg += encode_varint_u(0)
    msg += encode_varint_u(255)
    msg += encode_varint_u(4294967295)  # u32 max
    msg += encode_varint_u(3)           # 3 values
    msg += encode_f32(0.0)
    msg += encode_f32(-1.0)
    msg += encode_f32(100.5)
    msg += bytes([0x01])                # Some
    msg += encode_varint_u(2)           # StatusCode::Error
    msg += encode_varint_u(1024)        # error code: u16
    messages.append(bytes(msg))

    # 12: ConfigUpdate(param_id=0, value=Str(""))
    msg = bytearray()
    msg += encode_varint_u(1)
    msg += encode_varint_u(0)
    msg += encode_varint_u(2)        # Str
    msg += encode_string("")         # empty string
    messages.append(bytes(msg))

    # 13: Heartbeat(uptime_ms=0, free_mem=0)
    msg = bytearray()
    msg += encode_varint_u(2)
    msg += encode_varint_u(0)
    msg += encode_varint_u(0)
    messages.append(bytes(msg))

    # 14: Alert(level=Warn, source="battery", code=42)
    msg = bytearray()
    msg += encode_varint_u(3)
    msg += encode_varint_u(1)        # AlertLevel::Warn
    msg += encode_string("battery")
    msg += encode_varint_u(42)
    messages.append(bytes(msg))

    # 15: SensorReading(sensor_id=1000, timestamp=500000,
    #                    values=[1.0, 2.0, 3.0, 4.0, 5.0], status=None)
    msg = bytearray()
    msg += encode_varint_u(0)
    msg += encode_varint_u(1000)
    msg += encode_varint_u(500000)
    msg += encode_varint_u(5)        # 5 values
    msg += encode_f32(1.0)
    msg += encode_f32(2.0)
    msg += encode_f32(3.0)
    msg += encode_f32(4.0)
    msg += encode_f32(5.0)
    msg += bytes([0x00])             # None
    messages.append(bytes(msg))

    # 16: ConfigUpdate(param_id=50, value=Int(0))
    msg = bytearray()
    msg += encode_varint_u(1)
    msg += encode_varint_u(50)
    msg += encode_varint_u(0)        # Int
    msg += encode_varint_i(0)        # zigzag(0) = 0
    messages.append(bytes(msg))

    # 17: ConfigUpdate(param_id=60, value=Bool(false))
    msg = bytearray()
    msg += encode_varint_u(1)
    msg += encode_varint_u(60)
    msg += encode_varint_u(3)        # Bool
    msg += bytes([0x00])
    messages.append(bytes(msg))

    # --- Invalid messages (indices 18-24) ---

    # 18: Invalid discriminant (10) for Message (only 0-3 valid)
    msg = bytearray()
    msg += encode_varint_u(10)
    msg += bytes([0x01, 0x02, 0x03])  # trailing data
    messages.append(bytes(msg))

    # 19: Truncated SensorReading - discriminant + sensor_id only, no timestamp or later fields
    msg = bytearray()
    msg += encode_varint_u(0)        # SensorReading
    msg += encode_varint_u(42)       # sensor_id only
    messages.append(bytes(msg))

    # 20: Invalid bool value (0x02) in ConfigUpdate Bool variant
    msg = bytearray()
    msg += encode_varint_u(1)        # ConfigUpdate
    msg += encode_varint_u(100)
    msg += encode_varint_u(3)        # Bool
    msg += bytes([0x02])             # invalid bool value
    messages.append(bytes(msg))

    # 21: Varint overflow for u16 - 4 bytes exceeds max 3 for u16
    msg = bytearray()
    msg += encode_varint_u(0)        # SensorReading
    msg += bytes([0x80, 0x80, 0x80, 0x01])  # 4-byte varint for sensor_id (u16 max = 3)
    msg += encode_varint_u(0)
    msg += encode_varint_u(0)
    msg += bytes([0x00])
    messages.append(bytes(msg))

    # 22: Truncated varint - ends with continuation bit set
    msg = bytearray()
    msg += encode_varint_u(0)        # SensorReading
    msg += bytes([0x80])             # truncated varint for sensor_id
    messages.append(bytes(msg))

    # 23: Invalid UTF-8 in Alert source string
    msg = bytearray()
    msg += encode_varint_u(3)        # Alert
    msg += encode_varint_u(0)        # AlertLevel::Info
    msg += encode_varint_u(4)        # string length = 4
    msg += bytes([0xFF, 0xFE, 0x80, 0x41])  # invalid UTF-8
    msg += encode_varint_u(100)
    messages.append(bytes(msg))

    # 24: Invalid nested discriminant - StatusCode discriminant = 10 (only 0-2 valid)
    msg = bytearray()
    msg += encode_varint_u(0)        # SensorReading
    msg += encode_varint_u(1)        # sensor_id
    msg += encode_varint_u(0)        # timestamp
    msg += encode_varint_u(0)        # values: empty
    msg += bytes([0x01])             # status: Some
    msg += encode_varint_u(10)       # invalid StatusCode discriminant
    messages.append(bytes(msg))

    return messages


def main():
    if len(sys.argv) < 2:
        output_path = '/tmp/capture.bin'
    else:
        output_path = sys.argv[1]

    messages = build_messages()

    # Build capture: COBS-encode each message, separate with 0x00 sentinel
    capture = bytearray()
    for msg in messages:
        encoded = cobs_encode(msg)
        capture += encoded
        capture += bytes([0x00])

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'wb') as f:
        f.write(bytes(capture))

    print(f"Generated {len(messages)} messages, {len(capture)} bytes -> {output_path}")


if __name__ == '__main__':
    main()
