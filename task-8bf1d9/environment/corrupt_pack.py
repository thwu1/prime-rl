#!/usr/bin/env python3
"""Corrupt the pack file header by inflating the object count."""
import struct
import glob

pack_files = glob.glob("/app/repo/.git/objects/pack/*.pack")
assert len(pack_files) == 1, f"Expected 1 pack file, found {len(pack_files)}"
pack_path = pack_files[0]

with open(pack_path, "r+b") as f:
    # Verify magic
    magic = f.read(4)
    assert magic == b"PACK", f"Not a PACK file: {magic!r}"
    # Skip version (4 bytes)
    f.read(4)
    # Read current object count (big-endian uint32)
    count_bytes = f.read(4)
    count = struct.unpack(">I", count_bytes)[0]
    # Overwrite with inflated count (+3)
    f.seek(8)
    f.write(struct.pack(">I", count + 3))
    # The trailing 20-byte SHA-1 checksum is now also invalid
