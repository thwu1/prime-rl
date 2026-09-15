#!/usr/bin/env python3
"""Extract GZIP payload from a GWFW-format firmware image."""
import struct
import zlib
import sys
import os

def main():
    fw_path = sys.argv[1]
    work_dir = sys.argv[2]
    os.makedirs(work_dir, exist_ok=True)

    with open(fw_path, "rb") as f:
        data = f.read()

    # Parse 16-byte header
    magic = data[:4]
    if magic != b"GWFW":
        raise ValueError(f"Bad firmware magic: {magic!r}")

    fmt_version = struct.unpack("<I", data[4:8])[0]
    payload_len = struct.unpack("<I", data[8:12])[0]
    stored_crc = struct.unpack("<I", data[12:16])[0]

    payload = data[16:]
    if len(payload) != payload_len:
        raise ValueError(
            f"Payload length mismatch: header={payload_len}, file={len(payload)}"
        )

    actual_crc = zlib.crc32(payload) & 0xFFFFFFFF
    if actual_crc != stored_crc:
        raise ValueError(
            f"CRC32 mismatch: stored={stored_crc:#010x}, computed={actual_crc:#010x}"
        )

    gz_out = os.path.join(work_dir, "payload.gz")
    with open(gz_out, "wb") as f:
        f.write(payload)

    print(f"Header: magic=GWFW version={fmt_version} "
          f"payload_len={payload_len} crc32={stored_crc:#010x}")
    print(f"Extracted GZIP payload to {gz_out}")

if __name__ == "__main__":
    main()
