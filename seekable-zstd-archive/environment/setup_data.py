#!/usr/bin/env python3
"""
Generate a corrupted Zstandard Seekable Format archive for the repair task.

1. Generate 8 text segments deterministically
2. Compress each with zstd at varying levels
3. Build a valid seekable archive (with pure-Python XXH64 checksums)
4. Introduce 4 independent corruptions
5. Save the corrupted archive, individual reference frames, and manifest
"""

import hashlib
import json
import os
import struct
import subprocess

# --------------- Pure-Python XXH64 (no external deps) ---------------
_P1 = 0x9E3779B185EBCA87
_P2 = 0xC2B2AE3D27D4EB4F
_P3 = 0x165667B19E3779F9
_P4 = 0x85EBCA77C2B2AE63
_P5 = 0x27D4EB2F165667C5
_M  = 0xFFFFFFFFFFFFFFFF


def _r64(x, r):
    return ((x << r) | (x >> (64 - r))) & _M


def _rnd(acc, inp):
    acc = (acc + inp * _P2) & _M
    acc = _r64(acc, 31)
    return (acc * _P1) & _M


def _merge(acc, val):
    val = _rnd(0, val)
    acc = (acc ^ val) & _M
    return (acc * _P1 + _P4) & _M


def xxh64(data, seed=0):
    """Compute XXH64 digest. Returns a 64-bit unsigned integer."""
    n = len(data)
    p = 0
    if n >= 32:
        v1 = (seed + _P1 + _P2) & _M
        v2 = (seed + _P2) & _M
        v3 = seed & _M
        v4 = (seed - _P1) & _M
        while p + 32 <= n:
            v1 = _rnd(v1, int.from_bytes(data[p:p+8], 'little'))
            v2 = _rnd(v2, int.from_bytes(data[p+8:p+16], 'little'))
            v3 = _rnd(v3, int.from_bytes(data[p+16:p+24], 'little'))
            v4 = _rnd(v4, int.from_bytes(data[p+24:p+32], 'little'))
            p += 32
        h = (_r64(v1, 1) + _r64(v2, 7) + _r64(v3, 12) + _r64(v4, 18)) & _M
        h = _merge(h, v1)
        h = _merge(h, v2)
        h = _merge(h, v3)
        h = _merge(h, v4)
    else:
        h = (seed + _P5) & _M
    h = (h + n) & _M
    while p + 8 <= n:
        k = _rnd(0, int.from_bytes(data[p:p+8], 'little'))
        h = (_r64(h ^ k, 27) * _P1 + _P4) & _M
        p += 8
    while p + 4 <= n:
        k = int.from_bytes(data[p:p+4], 'little')
        h = (_r64(h ^ ((k * _P1) & _M), 23) * _P2 + _P3) & _M
        p += 4
    while p < n:
        h = (_r64(h ^ ((data[p] * _P5) & _M), 11) * _P1) & _M
        p += 1
    h = ((h ^ (h >> 33)) * _P2) & _M
    h = ((h ^ (h >> 29)) * _P3) & _M
    h = (h ^ (h >> 32)) & _M
    return h

# -------------------------------------------------------------------

TASK_DIR = "/opt/taskdata"
DATA_DIR = os.path.join(TASK_DIR, "frames")
MANIFEST_FILE = os.path.join(TASK_DIR, "manifest.json")
CORRUPTED_ARCHIVE = os.path.join(TASK_DIR, "corrupted_archive.zst")

os.makedirs(DATA_DIR, exist_ok=True)

SKIPPABLE_MAGIC_SEEKABLE = 0x184D2A5E
SEEKABLE_FOOTER_MAGIC = 0x8F92EAB1
NUM_FRAMES = 8


def generate_segment(part_num, num_lines=300):
    """Generate a deterministic log-like text segment for a given part number."""
    lines = []
    seed = f"seekable-zstd-bench-part-{part_num}"
    components = [
        "auth", "api", "db", "cache",
        "worker", "scheduler", "gateway", "monitor",
    ]
    levels = ["INFO", "DEBUG", "WARN", "ERROR", "TRACE"]
    actions = [
        "Request processed", "Connection established", "Cache miss detected",
        "Query executed", "Task scheduled", "Health check passed",
        "Rate limit applied", "Session refreshed", "Index rebuilt",
        "Batch committed", "Snapshot created", "Lease renewed",
        "Circuit breaker tripped", "Retry attempted", "Backpressure applied",
    ]
    for i in range(num_lines):
        h = hashlib.sha256(f"{seed}-line-{i}".encode()).hexdigest()
        month = (i % 12) + 1
        day = (i % 28) + 1
        hour = i % 24
        minute = i % 60
        second = int(h[:2], 16) % 60
        ts = f"2024-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}.{h[:6]}Z"
        level = levels[int(h[6:8], 16) % len(levels)]
        comp = components[int(h[8:10], 16) % len(components)]
        action = actions[int(h[10:12], 16) % len(actions)]
        sid = h[12:28]
        rid = h[28:36]
        bytes_val = int(h[36:40], 16)
        latency = int(h[40:44], 16) % 15000
        lines.append(
            f"{ts} [{level:5s}] [{comp:9s}] sid={sid} rid={rid} "
            f'msg="{action} for partition {part_num}, seq {i}" '
            f"bytes={bytes_val} latency_ms={latency}"
        )
    return "\n".join(lines) + "\n"


# Generate 8 segments with different compression levels
compression_levels = [1, 3, 5, 7, 9, 12, 15, 19]
segments = []
frame_data = []  # list of (compressed_bytes, decompressed_bytes)
full_content = b""

for i in range(NUM_FRAMES):
    segment = generate_segment(i)
    seg_bytes = segment.encode("utf-8")
    segments.append(segment)
    full_content += seg_bytes

    tmp_file = f"/tmp/segment_{i:02d}.txt"
    frame_file = os.path.join(DATA_DIR, f"frame_{i:02d}.zst")

    with open(tmp_file, "wb") as f:
        f.write(seg_bytes)

    level = compression_levels[i]
    subprocess.run(
        ["zstd", f"-{level}", "--check", "-f", tmp_file, "-o", frame_file],
        check=True,
        capture_output=True,
    )

    with open(frame_file, "rb") as f:
        compressed = f.read()

    frame_data.append((compressed, seg_bytes))
    os.remove(tmp_file)

# Compute expected SHA-256
expected_sha256 = hashlib.sha256(full_content).hexdigest()

# ---------------------------------------------------------------
# Build a VALID seekable archive, then corrupt it
# ---------------------------------------------------------------

# Concatenate all compressed frames
archive_bytes = b""
for compressed, _ in frame_data:
    archive_bytes += compressed

data_region_end = len(archive_bytes)

# Build seek table entries (each: comp_size + decomp_size + checksum, all 4-byte LE)
seek_entries = b""
for compressed, decompressed in frame_data:
    comp_size = len(compressed)
    decomp_size = len(decompressed)
    cksum = xxh64(decompressed, seed=0) & 0xFFFFFFFF
    seek_entries += struct.pack("<I", comp_size)
    seek_entries += struct.pack("<I", decomp_size)
    seek_entries += struct.pack("<I", cksum)

# Build footer: num_frames(4) + descriptor(1) + seekable_magic(4)
descriptor = 0x80  # Checksum_Flag set, all reserved/unused bits 0
footer = struct.pack("<I", NUM_FRAMES)
footer += struct.pack("B", descriptor)
footer += struct.pack("<I", SEEKABLE_FOOTER_MAGIC)

seek_content = seek_entries + footer

# Wrap in skippable frame: magic(4) + frame_size(4) + content
skippable_frame = struct.pack("<I", SKIPPABLE_MAGIC_SEEKABLE)
skippable_frame += struct.pack("<I", len(seek_content))
skippable_frame += seek_content

valid_archive = archive_bytes + skippable_frame

# ---------------------------------------------------------------
# Introduce 4 independent corruptions
# ---------------------------------------------------------------
corrupted = bytearray(valid_archive)

# Corruption 1: Frame 3 zstd magic bytes
#   zstd magic 0xFD2FB528 stored little-endian: \x28\xB5\x2F\xFD
#   Change first byte from 0x28 to 0x29 -> magic becomes 0xFD2FB529
#   Effect: zstd -d cannot decompress frame 3 (unrecognized magic)
frame3_offset = sum(len(frame_data[j][0]) for j in range(3))
assert corrupted[frame3_offset] == 0x28, f"Expected 0x28 at offset {frame3_offset}"
corrupted[frame3_offset] = 0x29

# Corruption 2: Seek table entry 5 -- swap compressed_size and decompressed_size
#   Effect: seek table entry 5 has sizes transposed
entry5_offset = data_region_end + 8 + 5 * 12
comp5 = struct.unpack("<I", corrupted[entry5_offset:entry5_offset + 4])[0]
decomp5 = struct.unpack("<I", corrupted[entry5_offset + 4:entry5_offset + 8])[0]
struct.pack_into("<I", corrupted, entry5_offset, decomp5)
struct.pack_into("<I", corrupted, entry5_offset + 4, comp5)

# Corruption 3: Seek table entries 2 and 6 -- checksums computed with seed=42
#   instead of the correct seed=0
#   Effect: checksum validation fails for these two entries
for bad_idx in [2, 6]:
    entry_offset = data_region_end + 8 + bad_idx * 12
    wrong_cksum = xxh64(frame_data[bad_idx][1], seed=42) & 0xFFFFFFFF
    struct.pack_into("<I", corrupted, entry_offset + 8, wrong_cksum)

# Corruption 4: Seek_Table_Descriptor reserved bit set
#   Spec says reserved bits (6-2) must be 0. Set bit 2 -> 0x84 instead of 0x80
#   Effect: compliant decoder rejects the seek table
descriptor_offset = data_region_end + 8 + NUM_FRAMES * 12 + 4
assert corrupted[descriptor_offset] == 0x80, f"Expected 0x80 at descriptor offset"
corrupted[descriptor_offset] = 0x84

# ---------------------------------------------------------------
# Write outputs
# ---------------------------------------------------------------

with open(CORRUPTED_ARCHIVE, "wb") as f:
    f.write(bytes(corrupted))

manifest = {
    "expected_sha256": expected_sha256,
    "num_frames": NUM_FRAMES,
    "notes": "Archive should be a valid Zstandard Seekable Format archive "
             "with checksums enabled. All frames were originally compressed "
             "with zstd --check at varying compression levels.",
}
with open(MANIFEST_FILE, "w") as f:
    json.dump(manifest, f, indent=2)

# Also create /app/output directory so it exists for the agent
os.makedirs("/app/output", exist_ok=True)

print(f"Generated {NUM_FRAMES} reference frames in {DATA_DIR}")
print(f"Corrupted archive written to {CORRUPTED_ARCHIVE}")
print(f"Expected SHA-256: {expected_sha256}")
print(f"Manifest written to {MANIFEST_FILE}")
