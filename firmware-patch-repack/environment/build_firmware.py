#!/usr/bin/env python3
"""Build a FWPK-format firmware image with encrypted config and HMAC integrity.

FWPK container layout:
  Header (44 bytes):
    [0:4]   Magic "FWPK"
    [4:6]   Version uint16 LE
    [6:8]   Num sections uint16 LE
    [8:12]  Directory offset uint32 LE
    [12:44] HMAC-SHA256 (32 bytes)

  Section directory (N entries x 64 bytes each):
    [0:16]  Name (null-padded ASCII)
    [16:20] Data offset uint32 LE
    [20:24] Data length uint32 LE
    [24:28] Flags uint32 LE (0=raw, 1=gzip, 2=encrypted)
    [28:32] Reserved uint32 LE
    [32:64] SHA-256 of section data (32 bytes)

  Section data (contiguous, in directory order)

HMAC-SHA256 is computed over all section data concatenated in directory order,
using the hmac.key section contents as the key.
"""
import struct
import hashlib
import hmac
import json
import sys


HMAC_KEY = bytes.fromhex("f0e1d2c3b4a596870011223344556677")
CONFIG_KEY = "a7c4e2f1b8d93056cafe1234dead5678"

HEADER_SIZE = 44
DIR_ENTRY_SIZE = 64


def xor_crypt(data, key):
    return bytes(d ^ key[i % len(key)] for i, d in enumerate(data))


def sha256(data):
    return hashlib.sha256(data).digest()


def main():
    payload_gz_path = sys.argv[1]
    config_path = sys.argv[2]
    output_path = sys.argv[3]

    with open(payload_gz_path, "rb") as f:
        payload_data = f.read()
    with open(config_path, "r") as f:
        config_text = f.read()

    meta = {
        "firmware_version": "1.3.7",
        "build_date": "2024-03-15",
        "device_model": "IoT-Gateway-Pro",
        "config_key": CONFIG_KEY,
    }
    meta_data = json.dumps(meta, indent=2).encode()

    config_key_bytes = bytes.fromhex(CONFIG_KEY)
    config_enc = xor_crypt(config_text.encode(), config_key_bytes)

    sections = [
        ("meta", meta_data, 0),
        ("payload", payload_data, 1),
        ("config.enc", config_enc, 2),
        ("hmac.key", HMAC_KEY, 0),
    ]

    num_sections = len(sections)
    dir_offset = HEADER_SIZE
    data_start = HEADER_SIZE + num_sections * DIR_ENTRY_SIZE

    entries = []
    offset = data_start
    for name, data, flags in sections:
        entries.append({
            "name": name,
            "data": data,
            "flags": flags,
            "offset": offset,
            "sha256": sha256(data),
        })
        offset += len(data)

    dir_bytes = b""
    for e in entries:
        dir_bytes += e["name"].encode().ljust(16, b"\x00")[:16]
        dir_bytes += struct.pack("<I", e["offset"])
        dir_bytes += struct.pack("<I", len(e["data"]))
        dir_bytes += struct.pack("<I", e["flags"])
        dir_bytes += struct.pack("<I", 0)
        dir_bytes += e["sha256"]

    all_data = b"".join(e["data"] for e in entries)
    h = hmac.new(HMAC_KEY, all_data, hashlib.sha256)
    hmac_value = h.digest()

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
    print(f"FWPK firmware: {total} bytes, {num_sections} sections")
    for e in entries:
        print(f"  {e['name']:16s} off={e['offset']:6d} len={len(e['data']):6d} flags={e['flags']}")


if __name__ == "__main__":
    main()
