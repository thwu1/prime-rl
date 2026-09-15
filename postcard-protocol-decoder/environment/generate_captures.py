#!/usr/bin/env python3
"""Generate binary capture files with COBS-framed postcard-rpc messages and CRC-8."""

import struct
import os


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


def encode_u8(v):
    return bytes([v & 0xFF])


def encode_u16(v):
    return encode_varint_unsigned(v)


def encode_i16(v):
    return encode_varint_unsigned(zigzag_encode(v))


def encode_u32(v):
    return encode_varint_unsigned(v)


def encode_i32(v):
    return encode_varint_unsigned(zigzag_encode(v))


def encode_u64(v):
    return encode_varint_unsigned(v)


def encode_f32(v):
    return struct.pack('<f', v)


def encode_string(s):
    b = s.encode('utf-8')
    return encode_varint_unsigned(len(b)) + b


def encode_bool(v):
    return bytes([0x01 if v else 0x00])


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


def make_frame(key_hex, seq_no, body):
    """Build a valid COBS-framed postcard-rpc message with CRC-8."""
    key_bytes = bytes.fromhex(key_hex)
    seq_bytes = encode_varint_unsigned(seq_no)
    payload = key_bytes + seq_bytes + body
    checksum = crc8(payload)
    raw = payload + bytes([checksum])
    return cobs_encode(raw) + b'\x00'


def make_corrupt_frame(key_hex, seq_no, body, corrupt_offset=10):
    """Build a frame with a corrupted payload byte (CRC will not match)."""
    key_bytes = bytes.fromhex(key_hex)
    seq_bytes = encode_varint_unsigned(seq_no)
    payload = key_bytes + seq_bytes + body
    checksum = crc8(payload)
    corrupted = bytearray(payload)
    idx = min(corrupt_offset, len(corrupted) - 1)
    corrupted[idx] ^= 0x04
    raw = bytes(corrupted) + bytes([checksum])
    return cobs_encode(raw) + b'\x00'


SENSOR_KEY = "a1b2c3d4e5f60718"
MOTOR_KEY = "1234567890abcdef"
STATUS_KEY = "fedcba9876543210"
ALERT_KEY = "55aa55aa55aa55aa"

# === Valid messages ===

# SensorReading(sensor_id=1023, temperature=-15, humidity=65.5, label="temp_a")
body1 = (encode_u16(1023) + encode_i32(-15) +
         encode_f32(65.5) + encode_string("temp_a"))

# MotorCommand(motor_idx=3, speed=-500, direction=Reverse(1), duration_ms=Some(2000))
body2 = (encode_u8(3) + encode_i16(-500) +
         encode_varint_unsigned(1) +
         bytes([0x01]) + encode_u32(2000))

# SensorReading(sensor_id=0, temperature=0, humidity=0.0, label="")
body3 = (encode_u16(0) + encode_i32(0) +
         encode_f32(0.0) + encode_string(""))

# DeviceStatus(uptime=86400, errors=[1,257], fw=(1,4,2), config={"gain":100,"offset":-5})
body4 = (encode_u64(86400) +
         encode_varint_unsigned(2) + encode_u16(1) + encode_u16(257) +
         encode_u8(1) + encode_u8(4) + encode_u8(2) +
         encode_varint_unsigned(2) +
         encode_string("gain") + encode_i32(100) +
         encode_string("offset") + encode_i32(-5))

# Alert(timestamp=5000, severity=Warning("temperature rising"), acknowledged=false)
body5 = (encode_u64(5000) +
         encode_varint_unsigned(1) + encode_string("temperature rising") +
         encode_bool(False))

# MotorCommand(motor_idx=0, speed=0, direction=Forward(0), duration_ms=None)
body6 = (encode_u8(0) + encode_i16(0) +
         encode_varint_unsigned(0) +
         bytes([0x00]))

# Alert(timestamp=5002, severity=Critical{code:1001, detail:"motor stall", recoverable:false}, ack=false)
body7 = (encode_u64(5002) +
         encode_varint_unsigned(2) +
         encode_u16(1001) + encode_string("motor stall") + encode_bool(False) +
         encode_bool(False))

# DeviceStatus(uptime=0, errors=[], fw=(0,0,1), config={})
body8 = (encode_u64(0) +
         encode_varint_unsigned(0) +
         encode_u8(0) + encode_u8(0) + encode_u8(1) +
         encode_varint_unsigned(0))

# Alert(timestamp=6000, severity=Info, acknowledged=true)
body9 = (encode_u64(6000) +
         encode_varint_unsigned(0) +
         encode_bool(True))

# === Corrupt message bodies (used only for corrupt frames) ===

# SensorReading(sensor_id=512, temperature=25, humidity=50.0, label="temp_b")
body_c1 = (encode_u16(512) + encode_i32(25) +
           encode_f32(50.0) + encode_string("temp_b"))

# Alert(timestamp=9999, severity=Info, acknowledged=true)
body_c2 = (encode_u64(9999) +
           encode_varint_unsigned(0) +
           encode_bool(True))

# DeviceStatus(uptime=999, errors=[42], fw=(2,0,0), config={})
body_c3 = (encode_u64(999) +
           encode_varint_unsigned(1) + encode_u16(42) +
           encode_u8(2) + encode_u8(0) + encode_u8(0) +
           encode_varint_unsigned(0))

# === Build session capture files ===
# session_alpha: 4 frames (valid, valid, CORRUPT, valid)
session_alpha = (make_frame(SENSOR_KEY, 1, body1) +
                 make_frame(MOTOR_KEY, 42, body2) +
                 make_corrupt_frame(SENSOR_KEY, 7, body_c1) +
                 make_frame(SENSOR_KEY, 2, body3))

# session_beta: 4 frames (valid, valid, valid, CORRUPT)
session_beta = (make_frame(STATUS_KEY, 100, body4) +
                make_frame(ALERT_KEY, 11, body5) +
                make_frame(MOTOR_KEY, 5, body6) +
                make_corrupt_frame(ALERT_KEY, 50, body_c2))

# session_gamma: 4 frames (CORRUPT, valid, valid, valid)
session_gamma = (make_corrupt_frame(STATUS_KEY, 99, body_c3) +
                 make_frame(ALERT_KEY, 12, body7) +
                 make_frame(STATUS_KEY, 0, body8) +
                 make_frame(ALERT_KEY, 20, body9))

os.makedirs('/app/captures', exist_ok=True)
for name, data in [('session_alpha', session_alpha),
                   ('session_beta', session_beta),
                   ('session_gamma', session_gamma)]:
    with open(f'/app/captures/{name}.bin', 'wb') as f:
        f.write(data)

print("Generated capture files with CRC-8 checksums successfully.")
