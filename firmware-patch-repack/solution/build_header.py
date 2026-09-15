#!/usr/bin/env python3
"""Reconstruct a GWFW firmware header around a GZIP payload."""
import struct
import zlib
import sys

def main():
    gz_path = sys.argv[1]
    output_path = sys.argv[2]

    with open(gz_path, "rb") as f:
        payload = f.read()

    magic = b"GWFW"
    fmt_version = struct.pack("<I", 2)
    payload_len = struct.pack("<I", len(payload))
    crc32_val = struct.pack("<I", zlib.crc32(payload) & 0xFFFFFFFF)

    header = magic + fmt_version + payload_len + crc32_val

    with open(output_path, "wb") as f:
        f.write(header)
        f.write(payload)

    print(f"Firmware written: {len(header)}-byte header + {len(payload)}-byte payload")
    print(f"  CRC32: {zlib.crc32(payload) & 0xFFFFFFFF:#010x}")

if __name__ == "__main__":
    main()
