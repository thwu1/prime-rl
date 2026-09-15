#!/usr/bin/env python3
"""Fix corrupted git pack file: correct the object count in header and recompute checksum.

"""

import glob
import hashlib
import struct
import sys
import zlib

pack_files = glob.glob("/app/repo/.git/objects/pack/*.pack")
if len(pack_files) != 1:
    print(f"Expected 1 pack file, found {len(pack_files)}", file=sys.stderr)
    sys.exit(1)

pack_path = pack_files[0]

with open(pack_path, "rb") as f:
    data = bytearray(f.read())

# Validate header
assert data[:4] == b"PACK", f"Not a PACK file: {data[:4]!r}"
version = struct.unpack_from(">I", data, 4)[0]
assert version == 2, f"Unexpected pack version: {version}"

claimed_count = struct.unpack_from(">I", data, 8)[0]
checksum_boundary = len(data) - 20  # Last 20 bytes = SHA-1 of all preceding bytes

# Parse pack entries to count actual objects
offset = 12  # Past the 12-byte header
actual_count = 0

while offset < checksum_boundary:
    # Variable-length type+size encoding
    byte = data[offset]
    obj_type = (byte >> 4) & 0x7
    size = byte & 0x0F
    shift = 4
    offset += 1

    while byte & 0x80:
        byte = data[offset]
        size |= (byte & 0x7F) << shift
        shift += 7
        offset += 1

    # OFS_DELTA (type 6): variable-length negative offset follows
    if obj_type == 6:
        byte = data[offset]
        offset += 1
        while byte & 0x80:
            byte = data[offset]
            offset += 1

    # REF_DELTA (type 7): 20-byte base object SHA-1 follows
    elif obj_type == 7:
        offset += 20

    # Decompress the zlib stream to find its exact boundary
    dec = zlib.decompressobj()
    remaining = bytes(data[offset:checksum_boundary])
    dec.decompress(remaining)
    consumed = len(remaining) - len(dec.unused_data)
    offset += consumed
    actual_count += 1

print(f"Pack header claims {claimed_count} objects, actually contains {actual_count}")

if claimed_count != actual_count:
    # Fix the object count
    struct.pack_into(">I", data, 8, actual_count)
    print(f"Corrected object count: {claimed_count} -> {actual_count}")

# Recompute the trailing SHA-1 checksum
new_checksum = hashlib.sha1(bytes(data[:checksum_boundary])).digest()
old_checksum = bytes(data[checksum_boundary:])
data[checksum_boundary:] = new_checksum

print(f"Old checksum: {old_checksum.hex()}")
print(f"New checksum: {new_checksum.hex()}")

with open(pack_path, "wb") as f:
    f.write(data)

print("Pack file repaired successfully.")
