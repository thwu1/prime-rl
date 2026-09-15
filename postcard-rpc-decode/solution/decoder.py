#!/usr/bin/env python3
"""
Full postcard-RPC bidirectional codec with FNV1a-64 key derivation,
round-trip encoding verification, invalid frame forensics, nested
EventKind enum handling, and cross-message thermal correlation.
"""
import json
import struct


# ---- FNV1a-64 key derivation ----

def fnv1a_64(data):
    h = 0xcbf29ce484222325
    for b in data:
        h ^= b
        h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def derive_key(path, schema):
    key_input = (path + '\x00' + schema).encode('utf-8')
    key_int = fnv1a_64(key_input)
    return struct.pack('<Q', key_int).hex()


# ---- COBS encode/decode ----

def cobs_decode(data):
    result = bytearray()
    idx = 0
    while idx < len(data):
        code = data[idx]
        idx += 1
        if code == 0:
            raise ValueError("Unexpected zero byte in COBS data")
        for _ in range(code - 1):
            if idx >= len(data):
                raise ValueError("COBS decode: unexpected end of data")
            result.append(data[idx])
            idx += 1
        if code < 0xFF and idx < len(data):
            result.append(0x00)
    return bytes(result)


def cobs_encode(data):
    result = bytearray([0])
    code_idx, code = 0, 1
    for byte in data:
        if byte == 0:
            result[code_idx] = code
            code, code_idx = 1, len(result)
            result.append(0)
        else:
            result.append(byte)
            code += 1
            if code == 0xFF:
                result[code_idx] = code
                code, code_idx = 1, len(result)
                result.append(0)
    result[code_idx] = code
    return bytes(result)


# ---- Varint / zigzag primitives ----

def decode_varint_u(data, offset, max_bytes=10):
    result, shift, count = 0, 0, 0
    while True:
        if offset >= len(data):
            raise ValueError("Varint: unexpected end of data")
        b = data[offset]
        result |= (b & 0x7F) << shift
        offset += 1
        count += 1
        if not (b & 0x80):
            break
        if count >= max_bytes:
            raise ValueError("Varint: too many bytes")
        shift += 7
    return result, offset


def encode_varint_u(value):
    r = bytearray()
    while value >= 0x80:
        r.append((value & 0x7F) | 0x80)
        value >>= 7
    r.append(value & 0x7F)
    return bytes(r)


def zigzag_decode(value):
    return -(value >> 1) - 1 if value & 1 else value >> 1


def zigzag_encode(value):
    return (value << 1) if value >= 0 else ((-value) << 1) - 1


# ---- Primitive decoders ----

def dec_u8(data, off):
    return data[off], off + 1

def dec_bool(data, off):
    return data[off] != 0, off + 1

def dec_u16(data, off):
    return decode_varint_u(data, off, 3)

def dec_i16(data, off):
    v, off = decode_varint_u(data, off, 3)
    return zigzag_decode(v), off

def dec_u32(data, off):
    return decode_varint_u(data, off, 5)

def dec_i32(data, off):
    v, off = decode_varint_u(data, off, 5)
    return zigzag_decode(v), off

def dec_string(data, off):
    length, off = decode_varint_u(data, off)
    s = data[off:off + length].decode('utf-8')
    return s, off + length

def dec_option_string(data, off):
    tag = data[off]
    off += 1
    if tag == 0x00:
        return None, off
    elif tag == 0x01:
        return dec_string(data, off)
    else:
        raise ValueError(f"Invalid option tag: {tag}")

def dec_seq_i16(data, off):
    count, off = decode_varint_u(data, off)
    values = []
    for _ in range(count):
        v, off = dec_i16(data, off)
        values.append(v)
    return values, off


# ---- Primitive encoders ----

def enc_u8(v):
    return bytes([v & 0xFF])

def enc_bool(v):
    return b'\x01' if v else b'\x00'

def enc_u16(v):
    return encode_varint_u(v)

def enc_i16(v):
    return encode_varint_u(zigzag_encode(v))

def enc_u32(v):
    return encode_varint_u(v)

def enc_i32(v):
    return encode_varint_u(zigzag_encode(v))

def enc_string(s):
    b = s.encode('utf-8')
    return encode_varint_u(len(b)) + b

def enc_option_string(v):
    if v is None:
        return b'\x00'
    return b'\x01' + enc_string(v)

def enc_seq_i16(vals):
    r = encode_varint_u(len(vals))
    for v in vals:
        r += enc_i16(v)
    return r


# ---- Frame header ----

def parse_header(data):
    if len(data) < 9:
        raise ValueError("Data too short for postcard-RPC header")
    key_hex = data[:8].hex()
    seq_no, offset = decode_varint_u(data, 8, 5)
    return key_hex, seq_no, offset


def build_header(key_hex, seq_no):
    key_bytes = bytes.fromhex(key_hex)
    return key_bytes + encode_varint_u(seq_no)


# ---- Message decoders ----

def decode_temp_reading(data, off):
    sensor_id, off = dec_u8(data, off)
    timestamp_ms, off = dec_u32(data, off)
    celsius_x100, off = dec_i16(data, off)
    valid, off = dec_bool(data, off)
    return {"sensor_id": sensor_id, "timestamp_ms": timestamp_ms,
            "celsius_x100": celsius_x100, "valid": valid}


def decode_motor_command(data, off):
    motor_id, off = dec_u8(data, off)
    speed_rpm, off = dec_i32(data, off)
    duration_ms, off = dec_u32(data, off)
    return {"motor_id": motor_id, "speed_rpm": speed_rpm,
            "duration_ms": duration_ms}


def decode_status_report(data, off):
    variant, off = decode_varint_u(data, off, 5)
    if variant == 0:
        return {"variant": "Idle"}
    elif variant == 1:
        val, off = dec_u16(data, off)
        return {"variant": "Active", "value": val}
    elif variant == 2:
        code, off = dec_u16(data, off)
        desc, off = dec_string(data, off)
        return {"variant": "Fault", "code": code, "description": desc}
    elif variant == 3:
        x, off = dec_i16(data, off)
        y, off = dec_i16(data, off)
        z, off = dec_i16(data, off)
        return {"variant": "Calibrating", "offsets": [x, y, z]}
    else:
        raise ValueError(f"Unknown StatusReport variant: {variant}")


def decode_batch_samples(data, off):
    batch_id, off = dec_u16(data, off)
    channel, off = dec_u8(data, off)
    samples, off = dec_seq_i16(data, off)
    return {"batch_id": batch_id, "channel": channel, "samples": samples}


def decode_config_entry(data, off):
    key, off = dec_string(data, off)
    value, off = dec_option_string(data, off)
    priority, off = dec_u8(data, off)
    return {"key": key, "value": value, "priority": priority}


def decode_system_event(data, off):
    timestamp_ms, off = dec_u32(data, off)
    source_id, off = dec_u8(data, off)
    variant, off = decode_varint_u(data, off, 5)
    if variant == 0:  # Boot
        firmware_version, off = dec_string(data, off)
        uptime_ms, off = dec_u32(data, off)
        return {"timestamp_ms": timestamp_ms, "source_id": source_id,
                "event": "Boot", "firmware_version": firmware_version,
                "uptime_ms": uptime_ms}
    elif variant == 1:  # Watchdog
        counter, off = dec_u16(data, off)
        return {"timestamp_ms": timestamp_ms, "source_id": source_id,
                "event": "Watchdog", "counter": counter}
    elif variant == 2:  # MemoryWarning
        used_kb, off = dec_u16(data, off)
        total_kb, off = dec_u16(data, off)
        allocator, off = dec_string(data, off)
        return {"timestamp_ms": timestamp_ms, "source_id": source_id,
                "event": "MemoryWarning", "used_kb": used_kb,
                "total_kb": total_kb, "allocator": allocator}
    elif variant == 3:  # Shutdown
        return {"timestamp_ms": timestamp_ms, "source_id": source_id,
                "event": "Shutdown"}
    else:
        raise ValueError(f"Unknown EventKind variant: {variant}")


# ---- Message encoders (for round-trip verification) ----

def encode_temp_reading(msg):
    return (enc_u8(msg["sensor_id"]) + enc_u32(msg["timestamp_ms"])
            + enc_i16(msg["celsius_x100"]) + enc_bool(msg["valid"]))


def encode_motor_command(msg):
    return (enc_u8(msg["motor_id"]) + enc_i32(msg["speed_rpm"])
            + enc_u32(msg["duration_ms"]))


def encode_status_report(msg):
    v = msg["variant"]
    if v == "Idle":
        return encode_varint_u(0)
    elif v == "Active":
        return encode_varint_u(1) + enc_u16(msg["value"])
    elif v == "Fault":
        return (encode_varint_u(2) + enc_u16(msg["code"])
                + enc_string(msg["description"]))
    elif v == "Calibrating":
        return (encode_varint_u(3) + enc_i16(msg["offsets"][0])
                + enc_i16(msg["offsets"][1]) + enc_i16(msg["offsets"][2]))
    else:
        raise ValueError(f"Unknown variant: {v}")


def encode_batch_samples(msg):
    return (enc_u16(msg["batch_id"]) + enc_u8(msg["channel"])
            + enc_seq_i16(msg["samples"]))


def encode_config_entry(msg):
    return (enc_string(msg["key"]) + enc_option_string(msg["value"])
            + enc_u8(msg["priority"]))


def encode_system_event(msg):
    body = enc_u32(msg["timestamp_ms"]) + enc_u8(msg["source_id"])
    ev = msg["event"]
    if ev == "Boot":
        body += encode_varint_u(0) + enc_string(msg["firmware_version"]) + enc_u32(msg["uptime_ms"])
    elif ev == "Watchdog":
        body += encode_varint_u(1) + enc_u16(msg["counter"])
    elif ev == "MemoryWarning":
        body += encode_varint_u(2) + enc_u16(msg["used_kb"]) + enc_u16(msg["total_kb"]) + enc_string(msg["allocator"])
    elif ev == "Shutdown":
        body += encode_varint_u(3)
    else:
        raise ValueError(f"Unknown event: {ev}")
    return body


# ---- Frame splitting ----

def split_frames(raw_data):
    frames = []
    current = bytearray()
    for byte in raw_data:
        if byte == 0x00:
            if current:
                frames.append(bytes(current))
                current = bytearray()
        else:
            current.append(byte)
    if current:
        frames.append(bytes(current))
    return frames


# ---- Main analysis ----

def main():
    schema_map = {
        "TempReading": (
            "sensor/temp",
            "struct:sensor_id:u8,timestamp_ms:u32,celsius_x100:i16,valid:bool"
        ),
        "MotorCommand": (
            "motor/set",
            "struct:motor_id:u8,speed_rpm:i32,duration_ms:u32"
        ),
        "StatusReport": (
            "device/status",
            "enum:Idle:unit,Active:u16,"
            "Fault:struct:code:u16,description:string,"
            "Calibrating:tuple:i16,i16,i16"
        ),
        "BatchSamples": (
            "data/batch",
            "struct:batch_id:u16,channel:u8,samples:seq:i16"
        ),
        "ConfigEntry": (
            "config/entry",
            "struct:key:string,value:option:string,priority:u8"
        ),
        "SystemEvent": (
            "system/event",
            "struct:timestamp_ms:u32,source_id:u8,"
            "event:enum:Boot:struct:firmware_version:string,uptime_ms:u32,"
            "Watchdog:u16,"
            "MemoryWarning:struct:used_kb:u16,total_kb:u16,allocator:string,"
            "Shutdown:unit"
        ),
    }

    key_to_type = {}
    all_keys = {}
    for name, (path, schema) in schema_map.items():
        hex_key = derive_key(path, schema)
        key_to_type[hex_key] = name
        all_keys[name] = hex_key

    decoders = {
        "TempReading": decode_temp_reading,
        "MotorCommand": decode_motor_command,
        "StatusReport": decode_status_report,
        "BatchSamples": decode_batch_samples,
        "ConfigEntry": decode_config_entry,
        "SystemEvent": decode_system_event,
    }

    encoders = {
        "TempReading": encode_temp_reading,
        "MotorCommand": encode_motor_command,
        "StatusReport": encode_status_report,
        "BatchSamples": encode_batch_samples,
        "ConfigEntry": encode_config_entry,
        "SystemEvent": encode_system_event,
    }

    with open('/app/capture.bin', 'rb') as f:
        raw_data = f.read()

    cobs_frames = split_frames(raw_data)

    valid_frames = 0
    invalid_frames = 0
    round_trip_success = 0
    message_counts = {t: 0 for t in decoders}
    invalid_frame_details = []

    temp_readings = []
    motor_commands = []
    status_reports = []
    batch_samples_list = []
    config_entries = []
    system_events = []

    collectors = {
        "TempReading": temp_readings,
        "MotorCommand": motor_commands,
        "StatusReport": status_reports,
        "BatchSamples": batch_samples_list,
        "ConfigEntry": config_entries,
        "SystemEvent": system_events,
    }

    for frame_idx, frame_data in enumerate(cobs_frames):
        raw_hex = frame_data.hex()
        raw_hex_prefix = raw_hex[:16] if len(raw_hex) > 16 else raw_hex

        try:
            decoded = cobs_decode(frame_data)
        except Exception:
            invalid_frames += 1
            invalid_frame_details.append({
                "frame_index": frame_idx,
                "raw_hex_prefix": raw_hex_prefix,
                "error_category": "cobs_error"
            })
            continue

        try:
            key_hex, seq_no, body_offset = parse_header(decoded)
        except Exception:
            invalid_frames += 1
            invalid_frame_details.append({
                "frame_index": frame_idx,
                "raw_hex_prefix": raw_hex_prefix,
                "error_category": "header_too_short"
            })
            continue

        if key_hex not in key_to_type:
            invalid_frames += 1
            invalid_frame_details.append({
                "frame_index": frame_idx,
                "raw_hex_prefix": raw_hex_prefix,
                "error_category": "unknown_key"
            })
            continue

        type_name = key_to_type[key_hex]
        try:
            msg = decoders[type_name](decoded, body_offset)
        except Exception:
            invalid_frames += 1
            invalid_frame_details.append({
                "frame_index": frame_idx,
                "raw_hex_prefix": raw_hex_prefix,
                "error_category": "deserialize_error"
            })
            continue

        msg["_seq_no"] = seq_no
        message_counts[type_name] += 1
        collectors[type_name].append(msg)
        valid_frames += 1

        # Round-trip verification
        re_body = encoders[type_name](msg)
        re_raw = build_header(key_hex, seq_no) + re_body
        re_cobs = cobs_encode(re_raw)
        if re_cobs == frame_data:
            round_trip_success += 1

    # --- Temperature analysis ---
    temp_values = [t["celsius_x100"] for t in temp_readings]

    # --- Calibration offset sums ---
    cal_sums = [0, 0, 0]
    for s in status_reports:
        if s["variant"] == "Calibrating":
            for i in range(3):
                cal_sums[i] += s["offsets"][i]

    # --- Fault-to-Idle recovery analysis ---
    fault_seqs = sorted(
        s["_seq_no"] for s in status_reports if s["variant"] == "Fault"
    )
    idle_seqs = sorted(
        s["_seq_no"] for s in status_reports if s["variant"] == "Idle"
    )
    recovery_gaps = []
    unrecovered = 0
    for fseq in fault_seqs:
        next_idle = None
        for iseq in idle_seqs:
            if iseq > fseq:
                next_idle = iseq
                break
        if next_idle is not None:
            recovery_gaps.append(next_idle - fseq)
        else:
            unrecovered += 1

    # --- Batch channel distribution ---
    channel_counts = {}
    for b in batch_samples_list:
        ch = str(b["channel"])
        channel_counts[ch] = channel_counts.get(ch, 0) + 1

    # --- SystemEvent summary ---
    boot_events = [e for e in system_events if e["event"] == "Boot"]
    watchdog_events = [e for e in system_events if e["event"] == "Watchdog"]
    memwarn_events = [e for e in system_events if e["event"] == "MemoryWarning"]
    shutdown_events = [e for e in system_events if e["event"] == "Shutdown"]

    system_event_summary = {
        "boot_count": len(boot_events),
        "watchdog_reset_total": sum(e["counter"] for e in watchdog_events),
        "memory_warning_count": len(memwarn_events),
        "shutdown_count": len(shutdown_events),
        "firmware_versions": sorted(set(e["firmware_version"] for e in boot_events)),
        "unique_source_ids": sorted(set(e["source_id"] for e in system_events)),
        "peak_memory_used_kb": max(e["used_kb"] for e in memwarn_events),
    }

    # --- Thermal correlation ---
    thermal_correlation = []
    for mw in memwarn_events:
        mw_ts = mw["timestamp_ms"]
        nearby = [t for t in temp_readings
                  if t["valid"] and abs(t["timestamp_ms"] - mw_ts) <= 2000]
        if nearby:
            mean_temp = sum(t["celsius_x100"] for t in nearby) / len(nearby)
        else:
            mean_temp = 0.0
        thermal_correlation.append({
            "event_timestamp_ms": mw_ts,
            "nearby_temp_count": len(nearby),
            "nearby_temp_mean_x100": mean_temp,
        })

    # --- Build output ---
    analysis = {
        "total_frames": valid_frames + invalid_frames,
        "valid_frames": valid_frames,
        "invalid_frames": invalid_frames,
        "derived_keys": {
            "StatusReport": all_keys["StatusReport"],
            "BatchSamples": all_keys["BatchSamples"],
            "ConfigEntry": all_keys["ConfigEntry"],
            "SystemEvent": all_keys["SystemEvent"],
        },
        "round_trip_success": round_trip_success,
        "message_counts": message_counts,
        "invalid_frame_details": sorted(invalid_frame_details,
                                        key=lambda d: d["frame_index"]),
        "temp_analysis": {
            "min_celsius_x100": min(temp_values),
            "max_celsius_x100": max(temp_values),
            "mean_celsius_x100": sum(temp_values) / len(temp_values),
            "unique_sensor_ids": sorted(set(t["sensor_id"]
                                            for t in temp_readings)),
            "invalid_count": sum(1 for t in temp_readings if not t["valid"]),
        },
        "motor_analysis": {
            "max_abs_speed_rpm": max(abs(m["speed_rpm"])
                                     for m in motor_commands),
            "total_duration_ms": sum(m["duration_ms"]
                                     for m in motor_commands),
        },
        "fault_sequence_numbers": fault_seqs,
        "calibration_offset_sums": cal_sums,
        "recovery_gaps": sorted(recovery_gaps),
        "unrecovered_faults": unrecovered,
        "batch_total_samples": sum(len(b["samples"])
                                   for b in batch_samples_list),
        "batch_channel_counts": channel_counts,
        "config_none_count": sum(1 for c in config_entries
                                 if c["value"] is None),
        "system_event_summary": system_event_summary,
        "thermal_correlation": thermal_correlation,
    }

    with open('/app/analysis.json', 'w') as f:
        json.dump(analysis, f, indent=2)

    print("Analysis written to /app/analysis.json")


if __name__ == '__main__':
    main()
