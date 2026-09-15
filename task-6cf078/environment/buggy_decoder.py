#!/usr/bin/env python3
"""Postcard-COBS decoder for sensor telemetry captures.

Reads /app/capture.bin and produces decoded output in /app/buggy_output/.

"""

import struct
import json
import csv
import os
import sys
from collections import defaultdict


def cobs_decode(data):
    """Decode COBS-encoded data (0x00 delimiter already stripped)."""
    output = bytearray()
    idx = 0
    while idx < len(data):
        code = data[idx]
        idx += 1
        if code == 0:
            raise ValueError("unexpected zero byte in COBS data")
        for _ in range(code - 1):
            if idx >= len(data):
                raise ValueError("COBS data truncated within block")
            output.append(data[idx])
            idx += 1
        if code < 0xFF and idx < len(data):
            output.append(0x00)
    return bytes(output)


def varint_decode(data, offset, max_bytes):
    """Decode a LEB128 varint from data at offset.
    max_bytes limits how many encoded bytes are consumed (type-specific).
    Returns (value, new_offset).
    """
    result = 0
    shift = 0
    for _ in range(max_bytes):
        if offset >= len(data):
            raise ValueError("unexpected end of data in varint")
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if (byte & 0x80) == 0:
            return result, offset
    raise ValueError(f"varint exceeds max encoded length ({max_bytes} bytes)")


def zigzag_decode(n):
    """Decode a zigzag-encoded unsigned integer back to signed."""
    return (n >> 1) ^ (n & 1)


def decode_reading(data):
    """Decode a SensorReading struct from postcard wire format bytes.
    Field order per schema.json:
      sensor_id:u16, timestamp_ms:u64, temperature_cdeg:i32(zigzag),
      humidity_pct_x10:u16, pressure_pa:u32, battery_mv:u16,
      status:enum(u32), sub_readings:seq<i16(zigzag)>
    """
    off = 0

    sensor_id, off = varint_decode(data, off, 3)   # u16: max 3 varint bytes
    if sensor_id > 0xFFFF:
        raise ValueError(f"sensor_id {sensor_id} exceeds u16 range")

    timestamp_ms, off = varint_decode(data, off, 10)  # u64: max 10 bytes

    temp_zz, off = varint_decode(data, off, 5)   # i32 zigzag: max 5 bytes
    temperature_cdeg = zigzag_decode(temp_zz)

    battery_mv, off = varint_decode(data, off, 3)   # u16
    if battery_mv > 0xFFFF:
        raise ValueError(f"battery_mv {battery_mv} exceeds u16 range")

    pressure_pa, off = varint_decode(data, off, 5)   # u32
    if pressure_pa > 0xFFFFFFFF:
        raise ValueError(f"pressure_pa {pressure_pa} exceeds u32 range")

    humidity_pct_x10, off = varint_decode(data, off, 3)    # u16
    if humidity_pct_x10 > 0xFFFF:
        raise ValueError(f"humidity_pct_x10 {humidity_pct_x10} exceeds u16 range")

    status_disc, off = varint_decode(data, off, 5)  # enum discriminant: varint(u32)
    status_names = ["Ok", "Error", "Warning", "Calibrating"]
    if status_disc >= len(status_names):
        raise ValueError(f"unknown status discriminant: {status_disc}")
    status = status_names[status_disc]

    seq_len, off = varint_decode(data, off, 10)   # seq length: varint(usize)
    sub_readings = []
    for _ in range(seq_len):
        v_zz, off = varint_decode(data, off, 3)  # i16 zigzag: max 3 bytes
        sub_readings.append(zigzag_decode(v_zz))

    return {
        "sensor_id": sensor_id,
        "timestamp_ms": timestamp_ms,
        "temperature_cdeg": temperature_cdeg,
        "humidity_pct_x10": humidity_pct_x10,
        "pressure_pa": pressure_pa,
        "battery_mv": battery_mv,
        "status": status,
        "sub_readings": sub_readings,
    }


def main():
    with open("/app/capture.bin", "rb") as f:
        raw = f.read()

    if len(raw) < 8:
        print("ERROR: File too short for header", file=sys.stderr)
        sys.exit(1)

    magic = raw[:4]
    if magic != b"PCOB":
        print(f"ERROR: Bad magic: {magic!r}", file=sys.stderr)
        sys.exit(1)

    total_frames_header = struct.unpack_from('<H', raw, 4)[0]
    stream = raw[8:]
    frames_raw = [f for f in stream.split(b'\x00') if f]

    print(f"Header says {total_frames_header} frames, found {len(frames_raw)} in stream")

    valid_readings = []
    corrupted_count = 0

    for frame_idx, cobs_data in enumerate(frames_raw):
        try:
            postcard_data = cobs_decode(cobs_data)
            reading = decode_reading(postcard_data)
            reading["frame_idx"] = frame_idx
            valid_readings.append(reading)
        except (ValueError, IndexError) as e:
            corrupted_count += 1
            print(f"  Frame {frame_idx}: corrupt ({e})", file=sys.stderr)

    os.makedirs("/app/buggy_output", exist_ok=True)

    # Summary
    unique_sensors = sorted(set(r["sensor_id"] for r in valid_readings))
    summary = {
        "total_frames": len(frames_raw),
        "valid_frames": len(valid_readings),
        "corrupted_frames": corrupted_count,
        "unique_sensors": unique_sensors,
    }
    with open("/app/buggy_output/summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    # Decoded CSV
    fieldnames = [
        "frame_idx", "sensor_id", "timestamp_ms", "temperature_cdeg",
        "humidity_pct_x10", "pressure_pa", "battery_mv", "status",
        "num_sub_readings"
    ]
    with open("/app/buggy_output/decoded.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in valid_readings:
            writer.writerow({
                "frame_idx": r["frame_idx"],
                "sensor_id": r["sensor_id"],
                "timestamp_ms": r["timestamp_ms"],
                "temperature_cdeg": r["temperature_cdeg"],
                "humidity_pct_x10": r["humidity_pct_x10"],
                "pressure_pa": r["pressure_pa"],
                "battery_mv": r["battery_mv"],
                "status": r["status"],
                "num_sub_readings": len(r["sub_readings"]),
            })

    # Per-sensor statistics
    sensor_temps = defaultdict(list)
    sensor_errors = defaultdict(int)
    sensor_sub_readings = defaultdict(int)

    for r in valid_readings:
        sid = r["sensor_id"]
        sensor_temps[sid].append(r["temperature_cdeg"])
        if r["status"] == "Error":
            sensor_errors[sid] += 1
        sensor_sub_readings[sid] += len(r["sub_readings"])

    per_sensor = {}
    for sid in unique_sensors:
        temps = sensor_temps[sid]
        per_sensor[str(sid)] = {
            "count": len(temps),
            "avg_temperature_cdeg": round(sum(temps) / len(temps), 2),
            "min_temperature_cdeg": min(temps),
            "max_temperature_cdeg": max(temps),
            "error_count": sensor_errors.get(sid, 0),
            "total_sub_readings": sensor_sub_readings.get(sid, 0),
        }

    with open("/app/buggy_output/per_sensor.json", "w") as f:
        json.dump(per_sensor, f, indent=2)

    # Anomalies
    anomalies = []
    for r in valid_readings:
        reasons = []
        if r["status"] == "Error":
            reasons.append("error_status")
        if r["temperature_cdeg"] > 450:
            reasons.append("high_temperature")
        if r["temperature_cdeg"] < -350:
            reasons.append("low_temperature")
        if reasons:
            anomalies.append({
                "frame_idx": r["frame_idx"],
                "sensor_id": r["sensor_id"],
                "reasons": sorted(reasons),
            })

    with open("/app/buggy_output/anomalies.json", "w") as f:
        json.dump(anomalies, f, indent=2)

    print(f"Done: {len(valid_readings)} valid, {corrupted_count} corrupted")


if __name__ == "__main__":
    main()
