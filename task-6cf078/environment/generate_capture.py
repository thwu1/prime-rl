#!/usr/bin/env python3
"""Generate capture.bin and reference_hex.json for the decoder forensics task.

"""

import random
import struct
import json
import os

random.seed(42)

TOTAL_FRAMES = 600
CORRUPT_INDICES = frozenset({
    7, 23, 48, 91, 137, 189, 234, 278, 312, 356, 401, 445, 478, 523, 567
})
SENSOR_IDS = [1, 2, 3, 5, 8]
STATUS_VARIANTS = [0, 1, 2, 3]  # Ok=0, Warning=1, Error=2, Calibrating=3
STATUS_WEIGHTS = [60, 25, 8, 7]
REFERENCE_INDICES = [0, 15, 42, 67, 100, 150, 200, 300, 400, 550]


def varint_encode(value):
    """Encode an unsigned integer as LEB128 varint."""
    if value < 0:
        raise ValueError("varint_encode requires non-negative value")
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def zigzag_encode(n):
    """Zigzag-encode a signed integer to unsigned."""
    if n >= 0:
        return 2 * n
    else:
        return -2 * n - 1


def cobs_encode(data):
    """COBS-encode a byte sequence (sentinel = 0x00)."""
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


def cobs_decode(data):
    """Decode COBS-encoded bytes."""
    output = bytearray()
    idx = 0
    while idx < len(data):
        code = data[idx]
        idx += 1
        if code == 0:
            raise ValueError("unexpected zero in COBS data")
        for _ in range(code - 1):
            if idx >= len(data):
                raise ValueError("truncated COBS block")
            output.append(data[idx])
            idx += 1
        if code < 0xFF and idx < len(data):
            output.append(0x00)
    return bytes(output)


def encode_reading(sensor_id, timestamp, temperature, humidity,
                   pressure, battery, status, sub_readings):
    """Encode a SensorReading in postcard wire format."""
    data = bytearray()
    data += varint_encode(sensor_id)
    data += varint_encode(timestamp)
    data += varint_encode(zigzag_encode(temperature))
    data += varint_encode(humidity)
    data += varint_encode(pressure)
    data += varint_encode(battery)
    data += varint_encode(status)
    data += varint_encode(len(sub_readings))
    for s in sub_readings:
        data += varint_encode(zigzag_encode(s))
    return bytes(data)


def main():
    os.makedirs('/app', exist_ok=True)

    readings = []
    stream = bytearray()
    stream += b'PCOB'
    stream += struct.pack('<HH', TOTAL_FRAMES, 0)

    for i in range(TOTAL_FRAMES):
        sensor_id = random.choice(SENSOR_IDS)
        timestamp = 1000000 + i * 1000 + random.randint(-50, 50)
        temperature = random.randint(-400, 500)
        humidity = random.randint(0, 1000)
        pressure = random.randint(95000, 105000)
        battery = random.randint(2800, 4200)
        status = random.choices(STATUS_VARIANTS, weights=STATUS_WEIGHTS)[0]
        num_sub = random.randint(0, 8)
        sub_readings = [random.randint(-500, 500) for _ in range(num_sub)]

        reading = {
            "sensor_id": sensor_id,
            "timestamp_ms": timestamp,
            "temperature_cdeg": temperature,
            "humidity_pct_x10": humidity,
            "pressure_pa": pressure,
            "battery_mv": battery,
            "status": ["Ok", "Warning", "Error", "Calibrating"][status],
            "sub_readings": sub_readings,
        }

        payload = encode_reading(sensor_id, timestamp, temperature, humidity,
                                 pressure, battery, status, sub_readings)

        if i in CORRUPT_INDICES:
            payload = payload[:3]
            readings.append(None)
        else:
            readings.append(reading)

        encoded = cobs_encode(payload)
        stream += encoded
        stream += b'\x00'

    with open('/app/capture.bin', 'wb') as f:
        f.write(bytes(stream))

    # Generate reference_hex.json with raw postcard payload hex for select frames
    raw_stream = bytes(stream[8:])
    cobs_frames = [f for f in raw_stream.split(b'\x00') if f]

    ref_hex = []
    for idx in REFERENCE_INDICES:
        if idx < len(cobs_frames) and readings[idx] is not None:
            cobs_data = cobs_frames[idx]
            postcard_data = cobs_decode(cobs_data)
            ref_hex.append({
                "frame_idx": idx,
                "cobs_encoded_hex": cobs_data.hex(),
                "postcard_payload_hex": postcard_data.hex(),
            })

    with open('/app/reference_hex.json', 'w') as f:
        json.dump(ref_hex, f, indent=2)

    print(f"Generated capture.bin: {len(stream)} bytes, {TOTAL_FRAMES} frames "
          f"({len(CORRUPT_INDICES)} corrupted)")
    print(f"Generated reference_hex.json: {len(ref_hex)} reference frames")


if __name__ == '__main__':
    main()
