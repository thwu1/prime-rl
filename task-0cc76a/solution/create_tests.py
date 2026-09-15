#!/usr/bin/env python3
"""
Create binary IMGP test input files that trigger each of the five bugs.
"""

import os
import struct


def make_header(width, height, channels, num_chunks):
    """Build a 14-byte IMGP header."""
    return (
        struct.pack("<I", 0x50474D49)   # magic "IMGP"
        + struct.pack("<I", width)
        + struct.pack("<I", height)
        + struct.pack("B", channels)
        + struct.pack("B", num_chunks)
    )


def make_chunk(chunk_type, data):
    """Build a chunk: type(1) + length(2) + data."""
    return struct.pack("B", chunk_type) + struct.pack("<H", len(data)) + data


def create_tests():
    out_dir = "/app/tests"
    os.makedirs(out_dir, exist_ok=True)

    # IMG001 -- integer overflow in buffer allocation
    # width=65536, height=65536, channels=4 -> 2^34 > UINT32_MAX
    with open(os.path.join(out_dir, "test_img001.img"), "wb") as f:
        f.write(make_header(65536, 65536, 4, 0))

    # IMG002 -- off-by-one palette index
    # palette has 3 entries (valid: 0,1,2); pixel index 3 == palette_count
    with open(os.path.join(out_dir, "test_img002.img"), "wb") as f:
        header = make_header(2, 2, 3, 2)
        palette_data = struct.pack("B", 3) + bytes([100, 100, 100] * 3)
        palette_chunk = make_chunk(0x01, palette_data)
        pixel_data = bytes([0, 1, 2, 3])
        pixel_chunk = make_chunk(0x02, pixel_data)
        f.write(header + palette_chunk + pixel_chunk)

    # IMG003 -- negative offset via signed/unsigned confusion
    # offset = -1 (int32_t), pixel_count = 16 (uint16_t)
    with open(os.path.join(out_dir, "test_img003.img"), "wb") as f:
        header = make_header(4, 4, 1, 1)
        offsets_data = struct.pack("<H", 1) + struct.pack("<i", -1)
        offsets_chunk = make_chunk(0x04, offsets_data)
        f.write(header + offsets_chunk)

    # IMG004 -- chunk claims 10 entries but only provides data for 1
    # 2 + 10*4 = 42 bytes needed; chunk only has 6 bytes
    with open(os.path.join(out_dir, "test_img004.img"), "wb") as f:
        header = make_header(4, 4, 1, 2)
        offsets_data = struct.pack("<H", 10) + struct.pack("<i", 1)
        offsets_chunk = make_chunk(0x04, offsets_data)
        comment_chunk = make_chunk(0x03, b"P" * 200)
        f.write(header + offsets_chunk + comment_chunk)

    # IMG005 -- RLE decompression overflow
    # 4x4 image, 1 channel -> pixel buffer = 16 bytes
    # RLE chunk: write_offset=10, run_len=20 -> 10+20=30 > 16
    with open(os.path.join(out_dir, "test_img005.img"), "wb") as f:
        header = make_header(4, 4, 1, 1)
        rle_data = struct.pack("<I", 10)         # write_offset
        rle_data += struct.pack("BB", 20, 0xFF)  # run_len=20, value=0xFF
        rle_chunk = make_chunk(0x05, rle_data)
        f.write(header + rle_chunk)

    print(f"Created test inputs in {out_dir}")


if __name__ == "__main__":
    create_tests()
