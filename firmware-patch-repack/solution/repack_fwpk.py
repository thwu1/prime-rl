#!/usr/bin/env python3
"""Repack sections into a FWPK firmware container with integrity chain."""
import struct
import hashlib
import hmac as hmac_mod
import sys

HEADER_SIZE = 44
DIR_ENTRY_SIZE = 64


def sha256(data):
    return hashlib.sha256(data).digest()


def main():
    meta_path = sys.argv[1]
    payload_path = sys.argv[2]
    config_enc_path = sys.argv[3]
    hmac_key_path = sys.argv[4]
    output_path = sys.argv[5]

    section_specs = [
        ("meta", meta_path, 0),
        ("payload", payload_path, 1),
        ("config.enc", config_enc_path, 2),
        ("hmac.key", hmac_key_path, 0),
    ]

    sections = []
    for name, path, flags in section_specs:
        with open(path, "rb") as f:
            data = f.read()
        sections.append((name, data, flags))

    num_sections = len(sections)
    dir_offset = HEADER_SIZE
    data_start = HEADER_SIZE + num_sections * DIR_ENTRY_SIZE

    entries = []
    offset = data_start
    for name, data, flags in sections:
        entries.append(
            {
                "name": name,
                "data": data,
                "flags": flags,
                "offset": offset,
                "sha256": sha256(data),
            }
        )
        offset += len(data)

    # Get HMAC key
    hmac_key = None
    for name, data, flags in sections:
        if name == "hmac.key":
            hmac_key = data
            break

    # Compute HMAC over all section data in directory order
    all_data = b"".join(e["data"] for e in entries)
    h = hmac_mod.new(hmac_key, all_data, hashlib.sha256)
    hmac_value = h.digest()

    # Build directory
    dir_bytes = b""
    for e in entries:
        name_padded = e["name"].encode().ljust(16, b"\x00")[:16]
        dir_bytes += name_padded
        dir_bytes += struct.pack("<I", e["offset"])
        dir_bytes += struct.pack("<I", len(e["data"]))
        dir_bytes += struct.pack("<I", e["flags"])
        dir_bytes += struct.pack("<I", 0)
        dir_bytes += e["sha256"]

    # Build header
    header = b"FWPK"
    header += struct.pack("<H", 2)
    header += struct.pack("<H", num_sections)
    header += struct.pack("<I", dir_offset)
    header += hmac_value

    with open(output_path, "wb") as f:
        f.write(header)
        f.write(dir_bytes)
        for e in entries:
            f.write(e["data"])

    total = len(header) + len(dir_bytes) + sum(len(e["data"]) for e in entries)
    print(f"FWPK written: {total} bytes, {num_sections} sections")


if __name__ == "__main__":
    main()
