#!/usr/bin/env python3
"""Generate capture.bin for postcard-RPC forensics task.

Produces a COBS-framed binary stream with postcard-serialized messages
matching the types defined in schema.rs, including deliberately corrupted
frames for forensic analysis. Keys are FNV1a-64 hashes of the RPC path +
canonical schema string.
"""
import struct, os

def fnv1a_64(data):
    h = 0xcbf29ce484222325
    for b in data:
        h ^= b
        h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h

def encode_varint_u(value):
    r = bytearray()
    while value >= 0x80:
        r.append((value & 0x7F) | 0x80)
        value >>= 7
    r.append(value & 0x7F)
    return bytes(r)

def zigzag(value):
    return (value << 1) if value >= 0 else ((-value) << 1) - 1

def enc_u8(v): return bytes([v & 0xFF])
def enc_u16(v): return encode_varint_u(v)
def enc_i16(v): return encode_varint_u(zigzag(v))
def enc_u32(v): return encode_varint_u(v)
def enc_i32(v): return encode_varint_u(zigzag(v))
def enc_bool(v): return b'\x01' if v else b'\x00'
def enc_str(s):
    b = s.encode('utf-8')
    return encode_varint_u(len(b)) + b
def enc_opt_str(v):
    if v is None: return b'\x00'
    return b'\x01' + enc_str(v)
def enc_seq_i16(vals):
    r = encode_varint_u(len(vals))
    for v in vals: r += enc_i16(v)
    return r

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

def build_frame(key, seq_no, body):
    header = struct.pack('<Q', key) + encode_varint_u(seq_no)
    return cobs_encode(header + body) + b'\x00'

# Message type definitions with canonical schema strings for key generation.
TYPES = {
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
        "enum:Idle:unit,Active:u16,Fault:struct:code:u16,description:string,"
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

keys = {}
for name, (path, schema) in TYPES.items():
    keys[name] = fnv1a_64((path + '\x00' + schema).encode('utf-8'))

# ---------- Generate message frames ----------
frames = []

# TempReading messages (seq 1-20): struct with u8, u32, i16, bool
temps = [
    (1,1000,2350,True),   (2,2000,-500,True),   (1,3000,2400,True),   (3,4000,3100,True),
    (1,5000,2280,True),   (2,6000,-1050,True),  (4,7000,5500,True),   (1,8000,2320,False),
    (3,9000,3050,True),   (2,10000,-200,True),  (5,11000,0,True),     (1,12000,2500,True),
    (3,13000,3200,True),  (2,14000,-800,True),  (4,15000,6000,True),  (1,16000,2450,True),
    (5,17000,100,False),  (2,18000,-1500,True), (3,19000,2800,True),  (1,20000,2600,True),
]
for i, (sid, ts, c, valid) in enumerate(temps):
    body = enc_u8(sid) + enc_u32(ts) + enc_i16(c) + enc_bool(valid)
    frames.append(build_frame(keys["TempReading"], i + 1, body))

# MotorCommand messages (seq 21-30): struct with u8, i32, u32
motors = [
    (1,1500,5000),(2,-800,3000),(1,0,0),(3,3200,10000),
    (2,-1200,7500),(1,2500,4000),(3,-4500,2000),(2,100,15000),
    (1,-50,500),(3,6000,1000),
]
for i, (mid, spd, dur) in enumerate(motors):
    body = enc_u8(mid) + enc_i32(spd) + enc_u32(dur)
    frames.append(build_frame(keys["MotorCommand"], 21 + i, body))

# Corrupted frame 1: COBS-decodable but too short for a valid header
frames.append(b'\x02\xAA\x00')

# StatusReport messages (seq 31-48): enum with Idle/Active/Fault/Calibrating variants
statuses = [
    ("Idle", None),
    ("Active", 1024),
    ("Idle", None),
    ("Active", 2048),
    ("Fault", {"code": 101, "description": "overtemp"}),
    ("Calibrating", (-50, 120, -5)),
    ("Idle", None),
    ("Active", 512),
    ("Fault", {"code": 202, "description": "overcurrent detected"}),
    ("Active", 4096),
    ("Calibrating", (100, -200, 300)),
    ("Idle", None),
    ("Fault", {"code": 303, "description": "sensor failure on bus 2"}),
    ("Active", 768),
    ("Calibrating", (-10, 0, 15)),
    ("Idle", None),
    ("Active", 3072),
    ("Fault", {"code": 404, "description": "watchdog timeout"}),
]
for i, (var, data) in enumerate(statuses):
    if var == "Idle":
        body = encode_varint_u(0)
    elif var == "Active":
        body = encode_varint_u(1) + enc_u16(data)
    elif var == "Calibrating":
        body = encode_varint_u(3) + enc_i16(data[0]) + enc_i16(data[1]) + enc_i16(data[2])
    else:  # Fault
        body = (encode_varint_u(2) + enc_u16(data["code"])
                + enc_str(data["description"]))
    frames.append(build_frame(keys["StatusReport"], 31 + i, body))

# Corrupted frame 2: valid COBS and header structure but unknown key
unk_raw = b'\x01\x02\x03\x04\x05\x06\x07\x08' + encode_varint_u(99) + b'\x42'
frames.append(cobs_encode(unk_raw) + b'\x00')

# BatchSamples messages (seq 49-58): struct with u16, u8, Vec<i16>
batches = [
    (1, 0, [100, -200, 300, -400, 500]),
    (2, 1, [1000, 2000, 3000]),
    (3, 0, [-100, -200, -300, -400, -500, -600, -700, -800]),
    (4, 2, [0, 0, 0, 0]),
    (5, 1, [32767, -32768]),
    (6, 0, list(range(1, 201))),   # 200 samples -- triggers COBS 254-byte block split
    (7, 3, [-1]),
    (8, 0, [100, 200, 300, 400, 500, 600]),
    (9, 1, [10000, -10000, 10000, -10000, 10000, -10000, 10000]),
    (10, 2, [42]),
]
for i, (bid, ch, samps) in enumerate(batches):
    body = enc_u16(bid) + enc_u8(ch) + enc_seq_i16(samps)
    frames.append(build_frame(keys["BatchSamples"], 49 + i, body))

# ConfigEntry messages (seq 59-66): struct with String, Option<String>, u8
configs = [
    ("sample_rate", "100", 1),
    ("threshold", "25.5", 2),
    ("device_name", "sensor_alpha", 3),
    ("debug_mode", None, 0),
    ("log_level", "warn", 1),
    ("max_retries", None, 2),
    ("firmware_version", "2.1.0", 255),
    ("calibration", None, 0),
]
for i, (k, v, p) in enumerate(configs):
    body = enc_str(k) + enc_opt_str(v) + enc_u8(p)
    frames.append(build_frame(keys["ConfigEntry"], 59 + i, body))

# SystemEvent messages (seq 67-74): struct with u32, u8, EventKind enum
events = [
    (1000, 1, "Boot", {"firmware_version": "2.1.0", "uptime_ms": 0}),
    (5000, 1, "MemoryWarning", {"used_kb": 450, "total_kb": 512, "allocator": "bump"}),
    (10000, 2, "Boot", {"firmware_version": "2.1.0", "uptime_ms": 0}),
    (15000, 1, "Watchdog", 3),
    (20000, 2, "MemoryWarning", {"used_kb": 500, "total_kb": 512, "allocator": "slab"}),
    (25000, 1, "Shutdown", None),
    (30000, 3, "Boot", {"firmware_version": "2.2.0-rc1", "uptime_ms": 120000}),
    (35000, 1, "Watchdog", 7),
]
for i, (ts, sid, var, data) in enumerate(events):
    body = enc_u32(ts) + enc_u8(sid)
    if var == "Boot":
        body += encode_varint_u(0) + enc_str(data["firmware_version"]) + enc_u32(data["uptime_ms"])
    elif var == "Watchdog":
        body += encode_varint_u(1) + enc_u16(data)
    elif var == "MemoryWarning":
        body += encode_varint_u(2) + enc_u16(data["used_kb"]) + enc_u16(data["total_kb"]) + enc_str(data["allocator"])
    elif var == "Shutdown":
        body += encode_varint_u(3)
    frames.append(build_frame(keys["SystemEvent"], 67 + i, body))

# Corrupted frame 3: bit-flip in a valid SystemEvent (Watchdog variant)
# -- produces a frame that COBS-decodes fine but has an unrecognized key
valid_body = enc_u32(40000) + enc_u8(1) + encode_varint_u(1) + enc_u16(99)
valid_raw = struct.pack('<Q', keys["SystemEvent"]) + encode_varint_u(75) + valid_body
valid_cobs = bytearray(cobs_encode(valid_raw))
valid_cobs[5] ^= 0x40  # Flip bit in key byte area
frames.append(bytes(valid_cobs) + b'\x00')

# Corrupted frame 4: truncated BatchSamples frame (COBS decode fails)
trunc_body = enc_u16(99) + enc_u8(0) + enc_seq_i16([100, 200, 300, 400])
trunc_raw = struct.pack('<Q', keys["BatchSamples"]) + encode_varint_u(76) + trunc_body
trunc_cobs = cobs_encode(trunc_raw)
frames.append(trunc_cobs[:-4] + b'\x00')  # Remove last 4 bytes

# Corrupted frame 5: byte duplication in ConfigEntry frame (COBS decode fails)
dup_body = enc_str("broken_key") + b'\x01' + enc_str("value") + enc_u8(5)
dup_raw = struct.pack('<Q', keys["ConfigEntry"]) + encode_varint_u(77) + dup_body
dup_cobs = bytearray(cobs_encode(dup_raw))
dup_cobs.insert(10, dup_cobs[10])  # Duplicate byte at position 10
frames.append(bytes(dup_cobs) + b'\x00')

# ---------- Write output ----------
os.makedirs('/app', exist_ok=True)
with open('/app/capture.bin', 'wb') as f:
    for fr in frames:
        f.write(fr)

print(f"Generated {len(frames)} frames in /app/capture.bin "
      f"({os.path.getsize('/app/capture.bin')} bytes)")
