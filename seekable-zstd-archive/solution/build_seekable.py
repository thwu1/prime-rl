#!/usr/bin/env python3
"""
Build a valid Zstandard Seekable Format archive from individual frames.

Reads compressed frames from /opt/taskdata/frames/, decompresses each to compute
sizes and xxH64 checksums, constructs a seek table, and writes the
complete seekable archive.
"""

import os
import struct
import subprocess

import xxhash

FRAMES_DIR = "/opt/taskdata/frames"
OUTPUT_FILE = "/app/output/seekable_archive.zst"

# Zstandard Seekable Format constants
SKIPPABLE_MAGIC_SEEKABLE = 0x184D2A5E
SEEKABLE_FOOTER_MAGIC = 0x8F92EAB1
NUM_FRAMES = 8


def main():
    frames = []

    for i in range(NUM_FRAMES):
        frame_path = os.path.join(FRAMES_DIR, f"frame_{i:02d}.zst")

        # Read compressed data
        with open(frame_path, "rb") as f:
            compressed = f.read()

        # Decompress to get decompressed content
        result = subprocess.run(
            ["zstd", "-d", "-c", frame_path],
            capture_output=True,
            check=True,
        )
        decompressed = result.stdout

        # Compute xxH64 checksum: seed=0, lower 32 bits
        digest = xxhash.xxh64(decompressed, seed=0).intdigest()
        checksum = digest & 0xFFFFFFFF

        frames.append(
            {
                "compressed": compressed,
                "compressed_size": len(compressed),
                "decompressed_size": len(decompressed),
                "checksum": checksum,
            }
        )

    # Build seek table entries
    # Each entry: compressed_size(4 LE) + decompressed_size(4 LE) + checksum(4 LE)
    seek_entries = b""
    for frame in frames:
        seek_entries += struct.pack("<I", frame["compressed_size"])
        seek_entries += struct.pack("<I", frame["decompressed_size"])
        seek_entries += struct.pack("<I", frame["checksum"])

    # Build seek table footer (9 bytes)
    # [Number_Of_Frames(4 LE)] [Seek_Table_Descriptor(1)] [Seekable_Magic_Number(4 LE)]
    descriptor = 0x80  # Checksum_Flag set (bit 7), all other bits 0
    footer = struct.pack("<I", NUM_FRAMES)
    footer += struct.pack("B", descriptor)
    footer += struct.pack("<I", SEEKABLE_FOOTER_MAGIC)

    # Full seek table content = entries + footer
    seek_content = seek_entries + footer

    # Wrap in skippable frame
    # [Skippable_Magic_Number(4 LE)] [Frame_Size(4 LE)] [content]
    skippable_frame = struct.pack("<I", SKIPPABLE_MAGIC_SEEKABLE)
    skippable_frame += struct.pack("<I", len(seek_content))
    skippable_frame += seek_content

    # Concatenate all compressed frames + seek table skippable frame
    archive = b""
    for frame in frames:
        archive += frame["compressed"]
    archive += skippable_frame

    # Write output
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "wb") as f:
        f.write(archive)

    print(f"Seekable archive written to {OUTPUT_FILE}")
    print(f"  Total size: {len(archive)} bytes")
    print(f"  Frames: {NUM_FRAMES}")
    print(f"  Seek table size: {len(skippable_frame)} bytes")
    for i, frame in enumerate(frames):
        print(
            f"  Frame {i}: comp={frame['compressed_size']}, "
            f"decomp={frame['decompressed_size']}, "
            f"cksum=0x{frame['checksum']:08X}"
        )


if __name__ == "__main__":
    main()
