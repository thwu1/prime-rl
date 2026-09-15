#!/usr/bin/env python3
"""
Git repository repair tool.
Diagnoses and fixes corruption in .git directory.
"""

import hashlib
import os
import struct
import sys
import zlib

REPO_PATH = "/app/repo"
GIT_DIR = os.path.join(REPO_PATH, ".git")

TYPE_NAMES = {1: "commit", 2: "tree", 3: "blob", 4: "tag"}


# ============================================================
# Phase 1: Fix HEAD symref
# ============================================================

def fix_head():
    """Inspect and repair .git/HEAD if it contains corruption."""
    head_path = os.path.join(GIT_DIR, "HEAD")
    with open(head_path, "rb") as f:
        data = f.read()

    if b"\x00" not in data and data.endswith(b"\n"):
        print("[HEAD] OK")
        return False

    # Extract valid content before any null bytes
    clean = data.split(b"\x00")[0]
    if not clean.endswith(b"\n"):
        clean = clean + b"\n"

    with open(head_path, "wb") as f:
        f.write(clean)

    print(f"[HEAD] Repaired — removed {len(data) - len(clean)} bytes of corruption")
    return True


# ============================================================
# Phase 2: Rebuild pack index
# ============================================================

def read_var_int_type_size(data, offset):
    """Read variable-length type+size from a pack entry header.
    First byte: bit 7 = continuation, bits 4-6 = type, bits 0-3 = size[3:0].
    Subsequent bytes: bit 7 = continuation, bits 0-6 = size[next 7 bits].
    """
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

    return obj_type, size, offset


def read_ofs_delta_offset(data, offset):
    """Read OFS_DELTA negative offset (variable-length, MSB continuation).
    Each continuation byte: value = ((value + 1) << 7) | (byte & 0x7F).
    """
    byte = data[offset]
    value = byte & 0x7F
    offset += 1

    while byte & 0x80:
        byte = data[offset]
        value = ((value + 1) << 7) | (byte & 0x7F)
        offset += 1

    return value, offset


def decompress_at(data, offset):
    """Decompress zlib data starting at offset in the pack data.
    Returns (decompressed_bytes, number_of_compressed_bytes_consumed).
    """
    d = zlib.decompressobj()
    result = d.decompress(data[offset:])
    consumed = len(data) - offset - len(d.unused_data)
    return result, consumed


def apply_delta(base_data, delta_data):
    """Apply git delta instructions to produce target data.
    Delta format: source_size (varint), target_size (varint), then instructions.
    Instruction 0x80+: copy from source (bit-flag controlled offset/size).
    Instruction 0x01-0x7F: insert N literal bytes.
    """
    pos = 0

    # Read source size
    src_size = 0
    shift = 0
    while True:
        byte = delta_data[pos]
        src_size |= (byte & 0x7F) << shift
        shift += 7
        pos += 1
        if not (byte & 0x80):
            break

    # Read target size
    tgt_size = 0
    shift = 0
    while True:
        byte = delta_data[pos]
        tgt_size |= (byte & 0x7F) << shift
        shift += 7
        pos += 1
        if not (byte & 0x80):
            break

    result = bytearray()

    while pos < len(delta_data):
        cmd = delta_data[pos]
        pos += 1

        if cmd & 0x80:
            # Copy instruction
            copy_off = 0
            copy_sz = 0

            if cmd & 0x01:
                copy_off = delta_data[pos]; pos += 1
            if cmd & 0x02:
                copy_off |= delta_data[pos] << 8; pos += 1
            if cmd & 0x04:
                copy_off |= delta_data[pos] << 16; pos += 1
            if cmd & 0x08:
                copy_off |= delta_data[pos] << 24; pos += 1

            if cmd & 0x10:
                copy_sz = delta_data[pos]; pos += 1
            if cmd & 0x20:
                copy_sz |= delta_data[pos] << 8; pos += 1
            if cmd & 0x40:
                copy_sz |= delta_data[pos] << 16; pos += 1

            if copy_sz == 0:
                copy_sz = 0x10000

            result.extend(base_data[copy_off:copy_off + copy_sz])

        elif cmd > 0:
            # Insert instruction
            result.extend(delta_data[pos:pos + cmd])
            pos += cmd
        else:
            raise ValueError("Invalid delta opcode 0x00")

    if len(result) != tgt_size:
        raise ValueError(
            f"Delta target size mismatch: got {len(result)}, expected {tgt_size}"
        )
    return bytes(result)


def find_pack_file():
    """Locate the single .pack file in the repository."""
    pack_dir = os.path.join(GIT_DIR, "objects", "pack")
    packs = [f for f in os.listdir(pack_dir) if f.endswith(".pack")]
    if not packs:
        print("[PACK] ERROR: No .pack file found")
        sys.exit(1)
    return os.path.join(pack_dir, packs[0])


def rebuild_pack_index(pack_path):
    """Parse the .pack file and generate a valid IDX v2 file.
    Returns the set of SHA-1 hashes of all objects in the pack.
    """
    with open(pack_path, "rb") as f:
        data = f.read()

    # Validate pack header
    magic = data[0:4]
    if magic != b"PACK":
        raise ValueError(f"Invalid pack magic: {magic!r}")
    version = struct.unpack(">I", data[4:8])[0]
    if version != 2:
        raise ValueError(f"Unsupported pack version: {version}")
    num_objects = struct.unpack(">I", data[8:12])[0]

    print(f"[PACK] Parsing: version {version}, {num_objects} objects")

    # Parse all entries
    entries = []
    offset_to_idx = {}
    offset = 12

    for i in range(num_objects):
        entry_start = offset
        obj_type, size, offset = read_var_int_type_size(data, offset)

        ofs_delta_base = None
        ref_delta_hash = None

        if obj_type == 6:  # OFS_DELTA
            neg_offset, offset = read_ofs_delta_offset(data, offset)
            ofs_delta_base = entry_start - neg_offset
        elif obj_type == 7:  # REF_DELTA
            ref_delta_hash = data[offset:offset + 20]
            offset += 20

        decompressed, consumed = decompress_at(data, offset)
        offset += consumed

        # CRC32 over raw pack entry bytes (header through compressed data)
        crc = zlib.crc32(data[entry_start:offset]) & 0xFFFFFFFF

        entries.append({
            "offset": entry_start,
            "type": obj_type,
            "crc32": crc,
            "data": decompressed,
            "ofs_delta_base": ofs_delta_base,
            "ref_delta_hash": ref_delta_hash,
        })
        offset_to_idx[entry_start] = i

    # Resolve delta chains — OFS_DELTA first (offset-based), then REF_DELTA
    def resolve(entry):
        if "resolved_data" in entry:
            return entry["resolved_data"], entry["resolved_type"]

        if entry["type"] in (1, 2, 3, 4):
            entry["resolved_data"] = entry["data"]
            entry["resolved_type"] = entry["type"]
            return entry["data"], entry["type"]

        if entry["type"] == 6:  # OFS_DELTA
            base_idx = offset_to_idx[entry["ofs_delta_base"]]
            base_data, base_type = resolve(entries[base_idx])
            resolved = apply_delta(base_data, entry["data"])
            entry["resolved_data"] = resolved
            entry["resolved_type"] = base_type
            return resolved, base_type

        return None, None  # REF_DELTA handled in phase 2

    # Phase 1: Resolve non-REF_DELTA objects and compute SHA-1s
    hash_to_idx = {}
    for idx, entry in enumerate(entries):
        if entry["type"] == 7:
            continue
        resolved_data, resolved_type = resolve(entry)
        type_name = TYPE_NAMES[resolved_type]
        header = f"{type_name} {len(resolved_data)}\0".encode()
        sha1 = hashlib.sha1(header + resolved_data).hexdigest()
        entry["sha1"] = sha1
        hash_to_idx[sha1] = idx

    # Phase 2: Resolve REF_DELTA objects
    for entry in entries:
        if entry["type"] != 7:
            continue
        ref_hex = entry["ref_delta_hash"].hex()
        if ref_hex not in hash_to_idx:
            raise ValueError(f"REF_DELTA base {ref_hex} not found")
        base_entry = entries[hash_to_idx[ref_hex]]
        base_data = base_entry["resolved_data"]
        base_type = base_entry["resolved_type"]
        resolved = apply_delta(base_data, entry["data"])
        entry["resolved_data"] = resolved
        entry["resolved_type"] = base_type
        type_name = TYPE_NAMES[base_type]
        header = f"{type_name} {len(resolved)}\0".encode()
        entry["sha1"] = hashlib.sha1(header + resolved).hexdigest()
        hash_to_idx[entry["sha1"]] = entries.index(entry)

    # Sort entries by SHA-1 for the index
    sorted_entries = sorted(entries, key=lambda e: e["sha1"])

    # Build IDX v2 binary
    idx = bytearray()

    # Magic number and version
    idx.extend(b"\xff\x74\x4f\x63")
    idx.extend(struct.pack(">I", 2))

    # Fanout table: 256 cumulative counts
    fanout = [0] * 256
    for entry in sorted_entries:
        first_byte = int(entry["sha1"][:2], 16)
        fanout[first_byte] += 1
    for i in range(1, 256):
        fanout[i] += fanout[i - 1]
    for count in fanout:
        idx.extend(struct.pack(">I", count))

    # Sorted SHA-1 hashes (20 bytes each)
    for entry in sorted_entries:
        idx.extend(bytes.fromhex(entry["sha1"]))

    # CRC32 values (4 bytes each, same order as sorted hashes)
    for entry in sorted_entries:
        idx.extend(struct.pack(">I", entry["crc32"]))

    # 4-byte offset table
    large_offsets = []
    for entry in sorted_entries:
        if entry["offset"] >= 0x80000000:
            idx.extend(struct.pack(">I", 0x80000000 | len(large_offsets)))
            large_offsets.append(entry["offset"])
        else:
            idx.extend(struct.pack(">I", entry["offset"]))

    # 8-byte large offset table (if any)
    for off in large_offsets:
        idx.extend(struct.pack(">Q", off))

    # Trailing pack SHA-1 (last 20 bytes of the .pack file)
    pack_sha1 = data[-20:]
    idx.extend(pack_sha1)

    # IDX file SHA-1 (over everything written so far)
    idx_sha1 = hashlib.sha1(bytes(idx)).digest()
    idx.extend(idx_sha1)

    # Write the .idx file
    idx_path = pack_path.replace(".pack", ".idx")
    with open(idx_path, "wb") as f:
        f.write(bytes(idx))

    print(f"[PACK] Rebuilt index: {len(sorted_entries)} objects -> {idx_path}")
    return {e["sha1"] for e in sorted_entries}


# ============================================================
# Phase 3: Fix corrupt loose objects
# ============================================================

def fix_corrupt_loose_objects(pack_hashes):
    """Find loose objects that fail decompression/validation.
    If the object exists in the pack, remove the corrupt loose copy.
    """
    objects_dir = os.path.join(GIT_DIR, "objects")
    fixed = 0

    for dirname in sorted(os.listdir(objects_dir)):
        if len(dirname) != 2 or not os.path.isdir(
            os.path.join(objects_dir, dirname)
        ):
            continue
        try:
            int(dirname, 16)
        except ValueError:
            continue

        dirpath = os.path.join(objects_dir, dirname)
        for filename in os.listdir(dirpath):
            obj_hash = dirname + filename
            if len(obj_hash) != 40:
                continue

            filepath = os.path.join(dirpath, filename)
            corrupt = False

            try:
                with open(filepath, "rb") as f:
                    raw = f.read()
                decompressed = zlib.decompress(raw)
                # Validate git object header: "type size\0data"
                null_pos = decompressed.index(b"\0")
                header = decompressed[:null_pos].decode("ascii")
                parts = header.split(" ")
                if (
                    len(parts) != 2
                    or parts[0] not in ("blob", "tree", "commit", "tag")
                ):
                    corrupt = True
                else:
                    size = int(parts[1])
                    body = decompressed[null_pos + 1:]
                    if len(body) != size:
                        corrupt = True
                    else:
                        computed = hashlib.sha1(decompressed).hexdigest()
                        if computed != obj_hash:
                            corrupt = True
            except Exception:
                corrupt = True

            if corrupt:
                if obj_hash in pack_hashes:
                    os.remove(filepath)
                    fixed += 1
                    print(f"[LOOSE] Removed corrupt object: {obj_hash}")
                    # Clean up empty directory
                    try:
                        os.rmdir(dirpath)
                    except OSError:
                        pass
                else:
                    print(
                        f"[LOOSE] WARNING: corrupt object {obj_hash} "
                        f"not in pack — cannot auto-remove"
                    )

    return fixed


# ============================================================
# Main repair flow
# ============================================================

def main():
    print("=" * 50)
    print("Git Repository Repair Tool")
    print("=" * 50)
    print()

    # Phase 1: Fix HEAD
    print("--- Phase 1: HEAD symref ---")
    fix_head()
    print()

    # Phase 2: Rebuild pack index
    print("--- Phase 2: Pack index ---")
    pack_path = find_pack_file()
    idx_path = pack_path.replace(".pack", ".idx")
    if os.path.exists(idx_path):
        print(f"[PACK] Index already exists at {idx_path}")
        # Could verify integrity here, but rebuild to be safe
    else:
        print("[PACK] No index file found — rebuilding from pack data")
    pack_hashes = rebuild_pack_index(pack_path)
    print()

    # Phase 3: Clean up corrupt loose objects
    print("--- Phase 3: Loose objects ---")
    fixed = fix_corrupt_loose_objects(pack_hashes)
    if fixed == 0:
        print("[LOOSE] No corrupt loose objects found")
    else:
        print(f"[LOOSE] Removed {fixed} corrupt loose object(s)")
    print()

    print("=" * 50)
    print("Repair complete")
    print("=" * 50)


if __name__ == "__main__":
    main()
