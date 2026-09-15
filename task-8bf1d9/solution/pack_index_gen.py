#!/usr/bin/env python3
"""
Git Pack Index v2 generator — reads a .pack file and writes the matching .idx.

Usage: pack_index_gen.py <pack-file>

Parses all entries (including OFS_DELTA and REF_DELTA), resolves delta chains,
computes SHA-1 identities and CRC32 checksums, builds the 256-entry fanout
table, and emits a valid Pack Index v2 file.

"""

import hashlib
import struct
import sys
import zlib

sys.setrecursionlimit(10000)

# Git object type constants
OBJ_COMMIT = 1
OBJ_TREE = 2
OBJ_BLOB = 3
OBJ_TAG = 4
OBJ_OFS_DELTA = 6
OBJ_REF_DELTA = 7

TYPE_LABELS = {
    OBJ_COMMIT: b"commit",
    OBJ_TREE: b"tree",
    OBJ_BLOB: b"blob",
    OBJ_TAG: b"tag",
}


def parse_pack(data):
    """Parse a Pack v2 file into a list of entry dicts.

    Returns (entries, pack_checksum) where each entry has:
        offset, type, crc32, raw_data, ofs_delta_base, ref_delta_base
    """
    if data[:4] != b"PACK":
        raise ValueError(f"Invalid pack magic: {data[:4]!r}")
    version = struct.unpack(">I", data[4:8])[0]
    if version != 2:
        raise ValueError(f"Unsupported pack version: {version}")
    num_objects = struct.unpack(">I", data[8:12])[0]
    pack_checksum = data[-20:]
    body_end = len(data) - 20

    entries = []
    offset = 12

    for _ in range(num_objects):
        entry_start = offset

        # Variable-length type + uncompressed size header
        byte = data[offset]
        offset += 1
        obj_type = (byte >> 4) & 0x7
        size = byte & 0x0F
        shift = 4
        while byte & 0x80:
            byte = data[offset]
            offset += 1
            size |= (byte & 0x7F) << shift
            shift += 7

        ofs_delta_base = None
        ref_delta_base = None

        if obj_type == OBJ_OFS_DELTA:
            byte = data[offset]
            offset += 1
            neg = byte & 0x7F
            while byte & 0x80:
                byte = data[offset]
                offset += 1
                neg = ((neg + 1) << 7) | (byte & 0x7F)
            ofs_delta_base = entry_start - neg

        elif obj_type == OBJ_REF_DELTA:
            ref_delta_base = data[offset : offset + 20]
            offset += 20

        # Decompress zlib stream
        dec = zlib.decompressobj()
        decompressed = dec.decompress(data[offset:body_end])
        consumed = len(data[offset:body_end]) - len(dec.unused_data)
        offset += consumed

        # CRC32 over raw pack bytes for this entry
        crc = zlib.crc32(data[entry_start:offset]) & 0xFFFFFFFF

        entries.append(
            {
                "offset": entry_start,
                "type": obj_type,
                "crc32": crc,
                "raw_data": decompressed,
                "ofs_delta_base": ofs_delta_base,
                "ref_delta_base": ref_delta_base,
            }
        )

    return entries, pack_checksum


def apply_delta(base, delta):
    """Apply a git binary delta instruction stream to base data."""
    pos = 0

    def read_size():
        nonlocal pos
        val = shift = 0
        while True:
            b = delta[pos]
            pos += 1
            val |= (b & 0x7F) << shift
            shift += 7
            if not (b & 0x80):
                return val

    _base_size = read_size()
    target_size = read_size()

    out = bytearray()
    while pos < len(delta):
        cmd = delta[pos]
        pos += 1

        if cmd & 0x80:
            # COPY from base
            cp_off = cp_sz = 0
            if cmd & 0x01:
                cp_off = delta[pos]; pos += 1
            if cmd & 0x02:
                cp_off |= delta[pos] << 8; pos += 1
            if cmd & 0x04:
                cp_off |= delta[pos] << 16; pos += 1
            if cmd & 0x08:
                cp_off |= delta[pos] << 24; pos += 1
            if cmd & 0x10:
                cp_sz = delta[pos]; pos += 1
            if cmd & 0x20:
                cp_sz |= delta[pos] << 8; pos += 1
            if cmd & 0x40:
                cp_sz |= delta[pos] << 16; pos += 1
            if cp_sz == 0:
                cp_sz = 0x10000
            out.extend(base[cp_off : cp_off + cp_sz])

        elif cmd:
            # INSERT literal bytes
            out.extend(delta[pos : pos + cmd])
            pos += cmd

        else:
            raise ValueError("Reserved delta instruction byte 0x00")

    if len(out) != target_size:
        raise ValueError(
            f"Delta target size mismatch: got {len(out)}, expected {target_size}"
        )
    return bytes(out)


def resolve_and_hash(entries):
    """Resolve all delta chains and compute SHA-1 for every entry.

    After this call each entry has a 'sha' key with a 20-byte digest.
    """
    offset_to_idx = {e["offset"]: i for i, e in enumerate(entries)}
    cache = {}  # index -> (resolved_type, resolved_content)

    def resolve(i):
        if i in cache:
            return cache[i]

        e = entries[i]

        if e["type"] in TYPE_LABELS:
            cache[i] = (e["type"], e["raw_data"])

        elif e["type"] == OBJ_OFS_DELTA:
            base_i = offset_to_idx[e["ofs_delta_base"]]
            base_type, base_data = resolve(base_i)
            cache[i] = (base_type, apply_delta(base_data, e["raw_data"]))

        elif e["type"] == OBJ_REF_DELTA:
            target_hex = e["ref_delta_base"].hex()
            # Resolve all non-REF_DELTA entries first to build SHA lookup
            for j in range(len(entries)):
                if entries[j]["type"] != OBJ_REF_DELTA and j not in cache:
                    resolve(j)
            # Find base by SHA
            found = False
            for j in range(len(entries)):
                if "sha" in entries[j] and entries[j]["sha"].hex() == target_hex:
                    base_type, base_data = cache[j]
                    cache[i] = (base_type, apply_delta(base_data, e["raw_data"]))
                    found = True
                    break
            if not found:
                raise ValueError(f"Cannot resolve REF_DELTA base {target_hex}")

        else:
            raise ValueError(f"Unknown object type: {e['type']}")

        # Compute SHA-1 identity: sha1("type len\0content")
        obj_type, content = cache[i]
        label = TYPE_LABELS[obj_type]
        header = label + b" " + str(len(content)).encode() + b"\0"
        entries[i]["sha"] = hashlib.sha1(header + content).digest()

        return cache[i]

    for i in range(len(entries)):
        resolve(i)


def write_idx(entries, pack_checksum, path):
    """Write a Pack Index v2 file.

    Layout:
      4B magic  \\xff tOc
      4B version 2
      256×4B fanout
      N×20B sorted SHA-1 table
      N×4B CRC32 table
      N×4B offset table (MSB set → large-offset index)
      [K×8B large-offset table]
      20B pack checksum
      20B index checksum
    """
    sorted_entries = sorted(entries, key=lambda e: e["sha"])
    n = len(sorted_entries)

    buf = bytearray()

    # Magic + version
    buf.extend(b"\xff\x74\x4f\x63")
    buf.extend(struct.pack(">I", 2))

    # Fanout table: fanout[i] = number of objects with first SHA byte <= i
    bucket_counts = [0] * 256
    for e in sorted_entries:
        bucket_counts[e["sha"][0]] += 1
    cumulative = 0
    for i in range(256):
        cumulative += bucket_counts[i]
        buf.extend(struct.pack(">I", cumulative))

    # SHA-1 table
    for e in sorted_entries:
        buf.extend(e["sha"])

    # CRC32 table
    for e in sorted_entries:
        buf.extend(struct.pack(">I", e["crc32"]))

    # Offset table
    large_offsets = []
    for e in sorted_entries:
        off = e["offset"]
        if off >= 0x80000000:
            large_offsets.append(off)
            buf.extend(struct.pack(">I", 0x80000000 | (len(large_offsets) - 1)))
        else:
            buf.extend(struct.pack(">I", off))

    # Large-offset table
    for lo in large_offsets:
        buf.extend(struct.pack(">Q", lo))

    # Pack file checksum (copied from pack trailer)
    buf.extend(pack_checksum)

    # Index file checksum (SHA-1 of everything above)
    buf.extend(hashlib.sha1(bytes(buf)).digest())

    with open(path, "wb") as f:
        f.write(buf)

    return n


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <pack-file>", file=sys.stderr)
        sys.exit(1)

    pack_path = sys.argv[1]
    with open(pack_path, "rb") as f:
        data = f.read()

    entries, pack_checksum = parse_pack(data)
    resolve_and_hash(entries)

    if pack_path.endswith(".pack"):
        idx_path = pack_path[:-5] + ".idx"
    else:
        idx_path = pack_path + ".idx"

    count = write_idx(entries, pack_checksum, idx_path)
    print(f"Indexed {count} objects -> {idx_path}")


if __name__ == "__main__":
    main()
