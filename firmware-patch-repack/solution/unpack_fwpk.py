#!/usr/bin/env python3
"""Unpack a FWPK firmware container into individual section files."""
import struct
import hashlib
import hmac as hmac_mod
import json
import sys
import os


def sha256(data):
    return hashlib.sha256(data).digest()


def main():
    fw_path = sys.argv[1]
    out_dir = sys.argv[2]

    with open(fw_path, "rb") as f:
        data = f.read()

    magic = data[:4]
    assert magic == b"FWPK", f"Bad magic: {magic!r}"
    version = struct.unpack("<H", data[4:6])[0]
    num_sections = struct.unpack("<H", data[6:8])[0]
    dir_offset = struct.unpack("<I", data[8:12])[0]
    stored_hmac = data[12:44]

    print(f"FWPK v{version}, {num_sections} sections, dir@{dir_offset}")

    sections_dir = os.path.join(out_dir, "sections")
    os.makedirs(sections_dir, exist_ok=True)

    entries = []
    for i in range(num_sections):
        base = dir_offset + i * 64
        name = data[base : base + 16].rstrip(b"\x00").decode("ascii")
        offset = struct.unpack("<I", data[base + 16 : base + 20])[0]
        length = struct.unpack("<I", data[base + 20 : base + 24])[0]
        flags = struct.unpack("<I", data[base + 24 : base + 28])[0]
        stored_sha = data[base + 32 : base + 64]
        section_data = data[offset : offset + length]

        computed_sha = sha256(section_data)
        sha_ok = computed_sha == stored_sha

        print(
            f"  [{i}] {name:16s} off={offset:6d} len={length:6d} "
            f"flags={flags} sha256={'OK' if sha_ok else 'MISMATCH'}"
        )

        section_path = os.path.join(sections_dir, name)
        with open(section_path, "wb") as f:
            f.write(section_data)

        entries.append(
            {"name": name, "offset": offset, "length": length, "flags": flags}
        )

    info = {
        "version": version,
        "num_sections": num_sections,
        "dir_offset": dir_offset,
        "entries": entries,
    }
    with open(os.path.join(out_dir, "info.json"), "w") as f:
        json.dump(info, f, indent=2)

    hmac_key_path = os.path.join(sections_dir, "hmac.key")
    if os.path.exists(hmac_key_path):
        with open(hmac_key_path, "rb") as f:
            hmac_key = f.read()
        all_data = b""
        for e in entries:
            with open(os.path.join(sections_dir, e["name"]), "rb") as f:
                all_data += f.read()
        h = hmac_mod.new(hmac_key, all_data, hashlib.sha256)
        hmac_ok = h.digest() == stored_hmac
        print(f"  HMAC: {'OK' if hmac_ok else 'MISMATCH'}")


if __name__ == "__main__":
    main()
