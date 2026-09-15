#!/usr/bin/env python3
"""
General-purpose parser for .vault binary archive format.

Encryption algorithms reverse engineered from the stripped binary
using radare2 disassembly analysis:

FILE ENCRYPTION (LCG-based stream cipher):
  - Initial state: seed_byte XOR crc32(filename_ascii)
  - For each byte i:
      state = (state * 0x41C64E6D + 0x3039) mod 2^32
      key_byte = (state >> 16) & 0xFF
      plaintext[i] = ciphertext[i] XOR key_byte

METADATA ENCRYPTION (different PRNG):
  - Initial state: seed_byte replicated to all 4 bytes (seed | seed<<8 | seed<<16 | seed<<24)
  - For each byte i:
      state = (state * 0x6C078965 + 1) mod 2^32
      key_byte = (state >> 24) & 0xFF
      plaintext[i] = ciphertext[i] XOR key_byte
"""
import struct
import zlib
import hashlib
import json
import os
import sys


def read_compact_int(data: bytes, offset: int) -> tuple:
    b0 = data[offset]
    if (b0 & 0x80) == 0:
        return (b0 & 0x7F, 1)
    elif (b0 & 0xC0) == 0x80:
        b1 = data[offset + 1]
        return (((b0 & 0x3F) << 8) | b1, 2)
    else:
        b1 = data[offset + 1]
        b2 = data[offset + 2]
        b3 = data[offset + 3]
        return (((b0 & 0x3F) << 24) | (b1 << 16) | (b2 << 8) | b3, 4)


def file_decrypt(data: bytes, filename: str, seed: int) -> bytes:
    state = seed ^ (zlib.crc32(filename.encode('ascii')) & 0xFFFFFFFF)
    result = bytearray(len(data))
    for i in range(len(data)):
        state = (state * 0x41C64E6D + 0x3039) & 0xFFFFFFFF
        key_byte = (state >> 16) & 0xFF
        result[i] = data[i] ^ key_byte
    return bytes(result)


def meta_decrypt(data: bytes, seed: int) -> bytes:
    state = (seed << 24) | (seed << 16) | (seed << 8) | seed
    result = bytearray(len(data))
    for i in range(len(data)):
        state = (state * 0x6C078965 + 1) & 0xFFFFFFFF
        key_byte = (state >> 24) & 0xFF
        result[i] = data[i] ^ key_byte
    return bytes(result)


def parse_vault(vault_path: str, output_dir: str):
    with open(vault_path, 'rb') as f:
        data = f.read()

    magic = data[0:4]
    if magic != b'\xC0\xDE\xFA\x17':
        raise ValueError(f"Invalid magic: {magic.hex()}")

    num_files = struct.unpack_from('<I', data, 8)[0]
    data_offset = struct.unpack_from('<I', data, 12)[0]
    meta_offset = struct.unpack_from('<I', data, 16)[0]
    xor_seed = data[20]

    entries = []
    pos = 24
    for _ in range(num_files):
        name_len, consumed = read_compact_int(data, pos)
        pos += consumed
        name = data[pos:pos + name_len].decode('ascii')
        pos += name_len
        compressed_size = struct.unpack_from('<I', data, pos)[0]; pos += 4
        decompressed_size = struct.unpack_from('<I', data, pos)[0]; pos += 4
        crc32_val = struct.unpack_from('<I', data, pos)[0]; pos += 4
        entry_flags = data[pos]; pos += 1
        entries.append({
            "name": name,
            "compressed_size": compressed_size,
            "decompressed_size": decompressed_size,
            "crc32": crc32_val,
            "flags": entry_flags,
            "encrypted": bool(entry_flags & 0x01),
        })

    extracted_dir = os.path.join(output_dir, "extracted")
    os.makedirs(extracted_dir, exist_ok=True)

    data_pos = data_offset
    for entry in entries:
        compressed_blob = data[data_pos:data_pos + entry["compressed_size"]]
        data_pos += entry["compressed_size"]

        decompressed = zlib.decompress(compressed_blob)

        if entry["encrypted"]:
            plaintext = file_decrypt(decompressed, entry["name"], xor_seed)
        else:
            plaintext = decompressed

        actual_crc = zlib.crc32(plaintext) & 0xFFFFFFFF
        if actual_crc != entry["crc32"]:
            raise ValueError(
                f"CRC32 mismatch for {entry['name']}: "
                f"got {actual_crc:#010x}, expected {entry['crc32']:#010x}"
            )

        safe_name = entry["name"].replace("/", "_").replace("\\", "_")
        with open(os.path.join(extracted_dir, safe_name), 'wb') as f:
            f.write(plaintext)

        entry["sha256"] = hashlib.sha256(plaintext).hexdigest()

    # Metadata
    meta_size = struct.unpack_from('<I', data, meta_offset)[0]
    meta_encrypted = data[meta_offset + 4:meta_offset + 4 + meta_size]
    meta_decrypted = meta_decrypt(meta_encrypted, xor_seed)
    metadata = json.loads(meta_decrypted.decode('utf-8'))

    # Write outputs
    file_table_out = [
        {
            "name": e["name"],
            "compressed_size": e["compressed_size"],
            "decompressed_size": e["decompressed_size"],
            "crc32": f"0x{e['crc32']:08X}",
            "flags": e["flags"],
            "encrypted": e["encrypted"],
            "sha256": e["sha256"],
        }
        for e in entries
    ]

    with open(os.path.join(output_dir, "file_table.json"), 'w') as f:
        json.dump(file_table_out, f, indent=2)
    with open(os.path.join(output_dir, "metadata.json"), 'w') as f:
        json.dump(metadata, f, indent=2)
    with open(os.path.join(output_dir, "verification.txt"), 'w') as f:
        f.write(metadata["verification_token"])
    with open(os.path.join(output_dir, "integrity.txt"), 'w') as f:
        f.write(metadata["integrity_hash"])

    print(f"Successfully parsed vault: {len(entries)} files extracted")


if __name__ == "__main__":
    vault_path = sys.argv[1] if len(sys.argv) > 1 else "/app/archive.vault"
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "/app/results"
    os.makedirs(output_dir, exist_ok=True)
    parse_vault(vault_path, output_dir)
