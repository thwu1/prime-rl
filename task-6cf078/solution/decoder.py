#!/usr/bin/env python3
"""
Correct COBS-postcard decoder with cross-language conformance check
and v2 schema migration analysis.

Reads /app/capture.bin, diagnoses bugs in /app/buggy_decoder.py,
produces correct decoded output, cross-validates against the C decoder,
and evaluates v2 schema backward compatibility.

"""

import struct
import json
import csv
import os
import sys
import subprocess
from collections import defaultdict


# ── Correct COBS decoder ──

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


# ── Correct varint decoder ──

def varint_decode(data, offset, max_bytes):
    """Decode a LEB128 varint from data at offset."""
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


# ── Correct zigzag decoder ──

def zigzag_decode(n):
    """Decode a zigzag-encoded unsigned integer back to signed.
    Correct formula: (n >> 1) ^ -(n & 1)
    """
    return (n >> 1) ^ -(n & 1)


# ── Correct struct decoder ──

def decode_reading(data):
    """Decode a SensorReading from postcard wire format bytes.
    Correct field order: sensor_id, timestamp_ms, temperature_cdeg,
    humidity_pct_x10, pressure_pa, battery_mv, status, sub_readings.
    """
    off = 0

    sensor_id, off = varint_decode(data, off, 3)
    if sensor_id > 0xFFFF:
        raise ValueError(f"sensor_id {sensor_id} exceeds u16 range")

    timestamp_ms, off = varint_decode(data, off, 10)

    temp_zz, off = varint_decode(data, off, 5)
    temperature_cdeg = zigzag_decode(temp_zz)

    # Correct order: humidity THEN pressure THEN battery
    humidity_pct_x10, off = varint_decode(data, off, 3)
    if humidity_pct_x10 > 0xFFFF:
        raise ValueError(f"humidity {humidity_pct_x10} exceeds u16 range")

    pressure_pa, off = varint_decode(data, off, 5)
    if pressure_pa > 0xFFFFFFFF:
        raise ValueError(f"pressure {pressure_pa} exceeds u32 range")

    battery_mv, off = varint_decode(data, off, 3)
    if battery_mv > 0xFFFF:
        raise ValueError(f"battery {battery_mv} exceeds u16 range")

    # Correct enum order: Ok=0, Warning=1, Error=2, Calibrating=3
    status_disc, off = varint_decode(data, off, 5)
    status_names = ["Ok", "Warning", "Error", "Calibrating"]
    if status_disc >= len(status_names):
        raise ValueError(f"unknown status discriminant: {status_disc}")
    status = status_names[status_disc]

    seq_len, off = varint_decode(data, off, 10)
    sub_readings = []
    for _ in range(seq_len):
        v_zz, off = varint_decode(data, off, 3)
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
    # ── Read and parse capture.bin ──
    with open("/app/capture.bin", "rb") as f:
        raw = f.read()

    if len(raw) < 8:
        print("ERROR: File too short for header", file=sys.stderr)
        sys.exit(1)

    magic = raw[:4]
    if magic != b"PCOB":
        print(f"ERROR: Bad magic: {magic!r}", file=sys.stderr)
        sys.exit(1)

    stream = raw[8:]
    frames_raw = [f for f in stream.split(b'\x00') if f]

    # ── Decode all frames ──
    valid_readings = []
    corrupted_count = 0

    for frame_idx, cobs_data in enumerate(frames_raw):
        try:
            postcard_data = cobs_decode(cobs_data)
            reading = decode_reading(postcard_data)
            reading["frame_idx"] = frame_idx
            valid_readings.append(reading)
        except (ValueError, IndexError):
            corrupted_count += 1

    os.makedirs("/app/results", exist_ok=True)

    # ── 1. Bug report ──
    bug_report = [
        {
            "component": "zigzag_decode",
            "bug_description": "The zigzag decode function uses (n >> 1) ^ (n & 1) "
                               "instead of the correct formula (n >> 1) ^ -(n & 1). "
                               "The missing negation causes all negative values to "
                               "decode as positive, making negative temperatures and "
                               "sub-readings appear as non-negative values.",
            "fix_description": "Change the return expression in zigzag_decode from "
                               "'(n >> 1) ^ (n & 1)' to '(n >> 1) ^ -(n & 1)'. "
                               "The negation of (n & 1) produces -1 for odd n, "
                               "which XORed with (n >> 1) correctly yields the "
                               "negative original value."
        },
        {
            "component": "status_enum_mapping",
            "bug_description": "The status_names list has Error and Warning swapped: "
                               "['Ok', 'Error', 'Warning', 'Calibrating'] instead of "
                               "['Ok', 'Warning', 'Error', 'Calibrating']. This causes "
                               "discriminant 1 (Warning) to display as Error and "
                               "discriminant 2 (Error) to display as Warning.",
            "fix_description": "Change status_names to ['Ok', 'Warning', 'Error', "
                               "'Calibrating'] to match the enum variant indices "
                               "defined in the schema (Ok=0, Warning=1, Error=2, "
                               "Calibrating=3)."
        },
        {
            "component": "field_order_swap",
            "bug_description": "The decoder reads battery_mv (u16) at the byte "
                               "position of humidity_pct_x10, and humidity_pct_x10 "
                               "(u16) at the byte position of battery_mv. Since "
                               "postcard encodes fields in declaration order "
                               "(humidity before battery per schema.json), reading "
                               "them in the wrong order swaps their values.",
            "fix_description": "Read humidity_pct_x10 first (immediately after "
                               "temperature_cdeg), then pressure_pa, then battery_mv. "
                               "This matches the field declaration order in "
                               "schema.json."
        }
    ]

    with open("/app/results/bug_report.json", "w") as f:
        json.dump(bug_report, f, indent=2)

    # ── 2. Summary ──
    unique_sensors = sorted(set(r["sensor_id"] for r in valid_readings))
    summary = {
        "total_frames": len(frames_raw),
        "valid_frames": len(valid_readings),
        "corrupted_frames": corrupted_count,
        "unique_sensors": unique_sensors,
    }
    with open("/app/results/summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    # ── 3. Decoded CSV ──
    fieldnames = [
        "frame_idx", "sensor_id", "timestamp_ms", "temperature_cdeg",
        "humidity_pct_x10", "pressure_pa", "battery_mv", "status",
        "num_sub_readings"
    ]
    with open("/app/results/decoded.csv", "w", newline="") as f:
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

    # ── 4. Per-sensor statistics ──
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

    with open("/app/results/per_sensor.json", "w") as f:
        json.dump(per_sensor, f, indent=2)

    # ── 5. Anomalies ──
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

    with open("/app/results/anomalies.json", "w") as f:
        json.dump(anomalies, f, indent=2)

    # ── 6. Conformance check: C decoder vs Python decoder ──
    c_output_path = "/tmp/c_decoder_output.json"
    if os.path.isfile(c_output_path):
        with open(c_output_path) as f:
            c_frames = json.load(f)
    else:
        # Try running C decoder directly
        result = subprocess.run(
            ["/app/libcobs/decode_capture", "/app/capture.bin"],
            capture_output=True, timeout=30
        )
        c_frames = json.loads(result.stdout.decode())

    c_valid = len(c_frames)
    py_valid = len(valid_readings)
    compared = min(c_valid, py_valid)
    matching = 0
    discrepancies = []

    for i in range(compared):
        c = c_frames[i]
        p = valid_readings[i]
        match = (
            c["frame_idx"] == p["frame_idx"] and
            c["sensor_id"] == p["sensor_id"] and
            c["timestamp_ms"] == p["timestamp_ms"] and
            c["temperature_cdeg"] == p["temperature_cdeg"] and
            c["humidity_pct_x10"] == p["humidity_pct_x10"] and
            c["pressure_pa"] == p["pressure_pa"] and
            c["battery_mv"] == p["battery_mv"] and
            c["status"] == p["status"] and
            c["num_sub_readings"] == len(p["sub_readings"])
        )
        if match:
            matching += 1
        else:
            discrepancies.append({
                "frame_idx": c["frame_idx"],
                "c_values": {k: c[k] for k in ["sensor_id", "temperature_cdeg",
                             "humidity_pct_x10", "pressure_pa", "battery_mv", "status"]},
                "python_values": {k: p[k] for k in ["sensor_id", "temperature_cdeg",
                                  "humidity_pct_x10", "pressure_pa", "battery_mv", "status"]},
            })

    conformance = {
        "c_decoder_valid_frames": c_valid,
        "python_decoder_valid_frames": py_valid,
        "frames_compared": compared,
        "frames_matching": matching,
        "discrepancies": discrepancies,
    }

    with open("/app/results/conformance.json", "w") as f:
        json.dump(conformance, f, indent=2)

    # ── 7. Migration analysis: v2 schema backward compatibility ──
    known_zone_sensors = {1: 10, 2: 20, 3: 30}

    # Count frames affected by each lossy change
    pressure_lossy_count = sum(
        1 for r in valid_readings if r["pressure_pa"] % 100 != 0
    )
    location_lossy_count = sum(
        1 for r in valid_readings if r["sensor_id"] not in known_zone_sensors
    )

    # A frame is fully lossless only if ALL changes are lossless for it
    fully_lossless = sum(
        1 for r in valid_readings
        if r["sensor_id"] in known_zone_sensors and r["pressure_pa"] % 100 == 0
    )
    lossy_total = len(valid_readings) - fully_lossless

    migration_analysis = {
        "schema_changes": [
            {
                "field": "location_zone",
                "change": "field_addition with partial sensor mapping",
                "compatibility": "lossy",
                "reason": "Zone mapping exists for sensors 1, 2, 3 but not for "
                          "sensors 5 and 8. Unmapped sensors receive default value "
                          "255 (unknown), introducing data that cannot be verified "
                          "against v1 original.",
                "affected_frame_count": location_lossy_count,
            },
            {
                "field": "temperature",
                "change": "unit scaling centidegrees to millidegrees (multiply by 10)",
                "compatibility": "lossless",
                "reason": "Integer multiplication by 10 is exact. Maximum v1 value "
                          "~500 cdeg becomes 5000 mdeg, well within i32 range. "
                          "Reverse conversion divides by 10 exactly.",
                "affected_frame_count": 0,
            },
            {
                "field": "pressure",
                "change": "type narrowing u32 Pascals to u16 hectopascals (divide by 100)",
                "compatibility": "lossy",
                "reason": "Integer division by 100 truncates the remainder. Frames "
                          "where pressure_pa is not exactly divisible by 100 lose "
                          "sub-hectopascal precision. The conversion is irreversible.",
                "affected_frame_count": pressure_lossy_count,
            },
            {
                "field": "status",
                "change": "enum reorder (Warning/Error swap) and new Maintenance variant",
                "compatibility": "lossless",
                "reason": "The discriminant mapping is unambiguous: v1 Ok(0)→v2 Ok(0), "
                          "v1 Warning(1)→v2 Warning(2), v1 Error(2)→v2 Error(1), "
                          "v1 Calibrating(3)→v2 Calibrating(3). No information is lost "
                          "since the semantic meaning is preserved.",
                "affected_frame_count": 0,
            },
            {
                "field": "sub_readings",
                "change": "element type widening i16 to i32",
                "compatibility": "lossless",
                "reason": "Every i16 value fits within i32 range. The wider type "
                          "can represent the original value exactly. Reverse "
                          "conversion is safe as long as values stay within i16 range.",
                "affected_frame_count": 0,
            },
        ],
        "total_valid_frames": len(valid_readings),
        "fully_lossless_frames": fully_lossless,
        "lossy_frames": lossy_total,
    }

    with open("/app/results/migration_analysis.json", "w") as f:
        json.dump(migration_analysis, f, indent=2)

    print(f"Done: {len(valid_readings)} valid, {corrupted_count} corrupted")
    print(f"Sensors: {unique_sensors}")
    print(f"Anomalies: {len(anomalies)}")
    print(f"Conformance: {matching}/{compared} matching, "
          f"{len(discrepancies)} discrepancies")
    print(f"Migration: {fully_lossless} lossless, {lossy_total} lossy")


if __name__ == "__main__":
    main()
