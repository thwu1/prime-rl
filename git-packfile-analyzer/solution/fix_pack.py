#!/usr/bin/env python3
"""Fix packfile version and trailing SHA-1 checksum."""

import glob
import hashlib
import struct

pack_files = glob.glob('/app/repo/.git/objects/pack/*.pack')

for pack_file in pack_files:
    with open(pack_file, 'rb') as f:
        data = bytearray(f.read())

    # Verify magic bytes
    assert data[:4] == b'PACK', f"Not a valid pack file: {pack_file}"

    # Read and fix version (bytes 4-7, big-endian uint32)
    version = struct.unpack('>I', data[4:8])[0]
    if version != 2:
        print(f"Pack version is {version}, fixing to 2")
        data[4:8] = struct.pack('>I', 2)

    # Compute correct trailing SHA-1 checksum over all data except last 20 bytes
    correct_checksum = hashlib.sha1(bytes(data[:-20])).digest()
    current_checksum = bytes(data[-20:])

    if current_checksum != correct_checksum:
        print(f"Pack checksum mismatch, fixing")
        print(f"  Current:  {current_checksum.hex()}")
        print(f"  Correct:  {correct_checksum.hex()}")
        data[-20:] = correct_checksum

    with open(pack_file, 'wb') as f:
        f.write(data)

    print(f"Pack file repaired: {pack_file}")
