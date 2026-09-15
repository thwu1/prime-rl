#!/usr/bin/env python3
"""
Diagnose and repair a corrupted Zstandard Seekable Format archive.

Strategy:
1. Read corrupted archive and individual reference frames
2. Compare data region byte-by-byte to find frame-level corruptions
3. Rebuild seek table from scratch using correct frame data
4. Produce valid repaired archive
"""

import json
import os
import struct
import subprocess

# --------------- Pure-Python XXH64 (spec-compliant, no external deps) ------
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

CORRUPTED_PATH = "/opt/taskdata/corrupted_archive.zst"
FRAMES_DIR = "/opt/taskdata/frames"
MANIFEST_PATH = "/opt/taskdata/manifest.json"
OUTPUT_PATH = "/app/output/repaired_archive.zst"

ZSTD_MAGIC = 0xFD2FB528
SKIPPABLE_MAGIC = 0x184D2A5E
SEEKABLE_MAGIC = 0x8F92EAB1


def main():
    # Load manifest
    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)
    num_frames = manifest["num_frames"]

    # Read corrupted archive
    with open(CORRUPTED_PATH, "rb") as f:
        corrupted = f.read()

    # Read individual reference frames
    ref_frames = []
    for i in range(num_frames):
        path = os.path.join(FRAMES_DIR, f"frame_{i:02d}.zst")
        with open(path, "rb") as f:
            ref_frames.append(f.read())

    # Expected data region: concatenation of all reference frames
    expected_data = b"".join(ref_frames)
    data_region_size = len(expected_data)

    # --- Diagnose data region corruptions ---
    print("=== Diagnosing data region ===")
    corruption_count = 0
    offset = 0
    for fi, frame in enumerate(ref_frames):
        frame_corruptions = 0
        for j in range(len(frame)):
            if offset + j < len(corrupted) and corrupted[offset + j] != frame[j]:
                frame_corruptions += 1
                print(
                    f"  Frame {fi}, byte {j}: archive has 0x{corrupted[offset+j]:02X}, "
                    f"expected 0x{frame[j]:02X}"
                )
        if frame_corruptions > 0:
            print(f"  -> Frame {fi}: {frame_corruptions} corrupted byte(s)")
            corruption_count += frame_corruptions
        offset += len(frame)
    print(f"Total data region corruptions: {corruption_count}")

    # --- Diagnose seek table ---
    print("\n=== Diagnosing seek table ===")
    footer_start = len(corrupted) - 9
    existing_num = struct.unpack("<I", corrupted[footer_start : footer_start + 4])[0]
    existing_desc = corrupted[footer_start + 4]
    existing_fmagic = struct.unpack("<I", corrupted[footer_start + 5 : footer_start + 9])[0]

    print(f"  Footer magic: 0x{existing_fmagic:08X} {'OK' if existing_fmagic == SEEKABLE_MAGIC else 'WRONG'}")
    print(f"  Frame count: {existing_num} {'OK' if existing_num == num_frames else 'WRONG'}")
    print(f"  Descriptor: 0x{existing_desc:02X} {'OK' if existing_desc == 0x80 else 'WRONG'}")

    reserved_bits = (existing_desc >> 2) & 0x1F
    if reserved_bits != 0:
        print(f"  -> Reserved bits are non-zero: 0b{reserved_bits:05b}")

    has_cksum = bool(existing_desc & 0x80)
    entry_size = 12 if has_cksum else 8
    entries_start = data_region_size + 8

    for i in range(num_frames):
        eoff = entries_start + i * entry_size
        comp = struct.unpack("<I", corrupted[eoff : eoff + 4])[0]
        decomp = struct.unpack("<I", corrupted[eoff + 4 : eoff + 8])[0]
        cksum = struct.unpack("<I", corrupted[eoff + 8 : eoff + 12])[0] if has_cksum else None

        ref_comp = len(ref_frames[i])
        result = subprocess.run(
            ["zstd", "-d", "-c", os.path.join(FRAMES_DIR, f"frame_{i:02d}.zst")],
            capture_output=True, check=True,
        )
        ref_decomp = len(result.stdout)
        ref_cksum = xxh64(result.stdout, seed=0) & 0xFFFFFFFF

        issues = []
        if comp != ref_comp:
            issues.append(f"comp_size {comp} != {ref_comp}")
        if decomp != ref_decomp:
            issues.append(f"decomp_size {decomp} != {ref_decomp}")
        if cksum is not None and cksum != ref_cksum:
            issues.append(f"checksum 0x{cksum:08X} != 0x{ref_cksum:08X}")
        if issues:
            print(f"  Entry {i}: {'; '.join(issues)}")

    # --- Rebuild repaired archive ---
    print("\n=== Rebuilding repaired archive ===")

    # Data region: use clean reference frames
    repaired = bytearray(expected_data)

    # Build seek table entries from reference frames
    seek_entries = b""
    for i in range(num_frames):
        comp_size = len(ref_frames[i])
        result = subprocess.run(
            ["zstd", "-d", "-c", os.path.join(FRAMES_DIR, f"frame_{i:02d}.zst")],
            capture_output=True, check=True,
        )
        decomp_size = len(result.stdout)
        cksum = xxh64(result.stdout, seed=0) & 0xFFFFFFFF

        seek_entries += struct.pack("<I", comp_size)
        seek_entries += struct.pack("<I", decomp_size)
        seek_entries += struct.pack("<I", cksum)

        print(f"  Frame {i}: comp={comp_size}, decomp={decomp_size}, cksum=0x{cksum:08X}")

    # Footer
    descriptor = 0x80  # Only Checksum_Flag set, reserved bits zero
    footer = struct.pack("<I", num_frames)
    footer += struct.pack("B", descriptor)
    footer += struct.pack("<I", SEEKABLE_MAGIC)

    seek_content = seek_entries + footer

    # Skippable frame wrapper
    skippable = struct.pack("<I", SKIPPABLE_MAGIC)
    skippable += struct.pack("<I", len(seek_content))
    skippable += seek_content

    repaired += skippable

    # Write output
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "wb") as f:
        f.write(bytes(repaired))

    print(f"\nRepaired archive written to {OUTPUT_PATH}")
    print(f"  Total size: {len(repaired)} bytes")
    print(f"  Data region: {data_region_size} bytes")
    print(f"  Seek table frame: {len(skippable)} bytes")

    # Verify
    result = subprocess.run(
        ["zstd", "-d", "-c", OUTPUT_PATH], capture_output=True
    )
    if result.returncode == 0:
        import hashlib
        sha = hashlib.sha256(result.stdout).hexdigest()
        print(f"  Decompressed SHA-256: {sha}")
        print(f"  Expected SHA-256:     {manifest['expected_sha256']}")
        print(f"  Match: {sha == manifest['expected_sha256']}")
    else:
        print(f"  WARNING: decompression failed: {result.stderr.decode()[:200]}")


if __name__ == "__main__":
    main()
