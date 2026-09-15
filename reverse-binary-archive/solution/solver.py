#!/usr/bin/env python3
"""
Solver for the binary archive extraction task.

Format overview (discovered via reverse engineering):

The raw file is a sequence of zlib-compressed blocks, each prefixed by:
    u32_le  decompressed_size
    u32_le  compressed_size
    <compressed_size bytes of zlib data>

The concatenated decompressed stream has:
  - Header: 4-byte magic (C0 DE BA 5E), u16 version, u16 flags
  - compact_int num_entries
  - compact_int key_schedule_len
  - key_material[key_schedule_len]
  - File table: num_entries entries, each with:
      compact_int name_len, name[name_len] (null-terminated),
      u32 virtual_offset (UNUSED — red herring),
      u32 data_size, u32 crc32, u8 encryption_flag
  - File data: concatenated in file-table order (linear, NOT at virtual offsets)
  - Encrypted entries use XOR: byte ^= key[(file_idx*7 + byte_off) % key_len]
  - keystore.nc is a nested container: magic 4E43, u8 count,
      then per entry: u8 name_len, name, u16_le data_len, data
"""

import struct
import zlib
import json
import os


def decompress_blocks(raw):
    """Decompress zlib-block-framed data."""
    out = bytearray()
    pos = 0
    while pos + 8 <= len(raw):
        dec_sz = struct.unpack_from('<I', raw, pos)[0]
        cmp_sz = struct.unpack_from('<I', raw, pos + 4)[0]
        pos += 8
        if pos + cmp_sz > len(raw):
            break
        chunk = zlib.decompress(raw[pos:pos + cmp_sz])
        assert len(chunk) == dec_sz, f"Block size mismatch: {len(chunk)} != {dec_sz}"
        out.extend(chunk)
        pos += cmp_sz
    return bytes(out)


def read_compact_int(data, off):
    """Decode a variable-length integer (high bits signal byte count)."""
    b0 = data[off]
    if b0 & 0x80 == 0:
        return b0, off + 1
    elif b0 & 0xC0 == 0x80:
        return ((b0 & 0x3F) << 8) | data[off + 1], off + 2
    elif b0 & 0xE0 == 0xC0:
        return (((b0 & 0x1F) << 16) | (data[off + 1] << 8)
                | data[off + 2]), off + 3
    else:
        return (((b0 & 0x0F) << 24) | (data[off + 1] << 16)
                | (data[off + 2] << 8) | data[off + 3]), off + 4


def xor_decrypt(data, file_index, key_material):
    """XOR-decrypt with rolling key derived from file index."""
    out = bytearray(len(data))
    km_len = len(key_material)
    for i in range(len(data)):
        out[i] = data[i] ^ key_material[(file_index * 7 + i) % km_len]
    return bytes(out)


def parse_nested_container(data):
    """Parse the NC (nested container) format."""
    assert data[0:2] == b'\x4E\x43', f"Bad NC magic: {data[0:2].hex()}"
    count = data[2]
    pos = 3
    entries = {}
    for _ in range(count):
        nlen = data[pos]; pos += 1
        name = data[pos:pos + nlen].decode('utf-8'); pos += nlen
        dlen = struct.unpack_from('<H', data, pos)[0]; pos += 2
        entries[name] = data[pos:pos + dlen].decode('utf-8'); pos += dlen
    return entries


def main():
    with open('/app/artifact.bin', 'rb') as f:
        raw = f.read()

    # --- Decompress zlib blocks ---
    stream = decompress_blocks(raw)
    pos = 0

    # --- Parse header ---
    magic = stream[pos:pos + 4]; pos += 4
    assert magic == b'\xC0\xDE\xBA\x5E', f"Unknown magic: {magic.hex()}"

    version = struct.unpack_from('<H', stream, pos)[0]; pos += 2
    flags = struct.unpack_from('<H', stream, pos)[0]; pos += 2

    num_entries, pos = read_compact_int(stream, pos)
    key_sched_len, pos = read_compact_int(stream, pos)
    key_material = stream[pos:pos + key_sched_len]; pos += key_sched_len

    # --- Parse file table ---
    file_table = []
    for _ in range(num_entries):
        name_len, pos = read_compact_int(stream, pos)
        name = stream[pos:pos + name_len].rstrip(b'\x00').decode('utf-8')
        pos += name_len
        voff = struct.unpack_from('<I', stream, pos)[0]; pos += 4
        size = struct.unpack_from('<I', stream, pos)[0]; pos += 4
        crc  = struct.unpack_from('<I', stream, pos)[0]; pos += 4
        enc  = stream[pos]; pos += 1
        file_table.append({
            'name': name, 'size': size, 'crc': crc, 'encrypted': enc == 1
        })

    # --- Extract file data (linear order, ignore virtual offsets) ---
    extracted = {}
    for i, entry in enumerate(file_table):
        raw_data = stream[pos:pos + entry['size']]
        pos += entry['size']

        if entry['encrypted']:
            data = xor_decrypt(raw_data, i, key_material)
        else:
            data = raw_data

        actual_crc = zlib.crc32(data) & 0xFFFFFFFF
        assert actual_crc == entry['crc'], (
            f"CRC mismatch for {entry['name']}: "
            f"expected {entry['crc']:#010x}, got {actual_crc:#010x}"
        )
        extracted[entry['name']] = data

    # --- Parse nested container inside decrypted keystore ---
    nc = parse_nested_container(extracted['keystore.nc'])

    # --- Write outputs ---
    os.makedirs('/app/output', exist_ok=True)

    with open('/app/output/token.txt', 'w') as f:
        f.write(nc['token'])

    manifest = {
        'num_files': num_entries,
        'file_names': sorted(e['name'] for e in file_table),
        'encrypted_count': sum(1 for e in file_table if e['encrypted']),
    }
    with open('/app/output/manifest.json', 'w') as f:
        json.dump(manifest, f, indent=2)

    with open('/app/output/credentials.txt', 'w') as f:
        f.write(extracted['credentials.enc'].decode('utf-8'))

    print(f"Token: {nc['token']}")
    print(f"Manifest: {json.dumps(manifest, indent=2)}")
    print("Extraction complete.")


if __name__ == '__main__':
    main()
