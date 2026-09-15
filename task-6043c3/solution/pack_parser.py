#!/usr/bin/env python3
"""Git pack file parser and index generator.


Reads objects from Git pack files with or without an index file,
resolves delta chains, and can regenerate pack index v2 files.
"""

import struct
import zlib
import sys
import os
import hashlib
import binascii

# Pack object type codes
OBJ_COMMIT = 1
OBJ_TREE = 2
OBJ_BLOB = 3
OBJ_TAG = 4
OBJ_OFS_DELTA = 6
OBJ_REF_DELTA = 7

TYPE_NAMES = {
    OBJ_COMMIT: "commit",
    OBJ_TREE: "tree",
    OBJ_BLOB: "blob",
    OBJ_TAG: "tag",
}


def read_size_type(data, pos):
    """Read type (3 bits) and size (variable-length) from pack entry header.

    Encoding: first byte has type in bits 6-4, size[3:0] in bits 3-0,
    continuation in bit 7. Subsequent bytes contribute 7 bits each to size.
    """
    byte = data[pos]
    obj_type = (byte >> 4) & 0x07
    size = byte & 0x0F
    shift = 4
    pos += 1
    while byte & 0x80:
        byte = data[pos]
        size |= (byte & 0x7F) << shift
        shift += 7
        pos += 1
    return obj_type, size, pos


def read_ofs_offset(data, pos):
    """Read OFS_DELTA negative offset varint.

    Uses a distinct encoding: offset = ((offset + 1) << 7) | (byte & 0x7F)
    for continuation bytes, which differs from the size varint.
    """
    byte = data[pos]
    offset = byte & 0x7F
    pos += 1
    while byte & 0x80:
        byte = data[pos]
        offset = ((offset + 1) << 7) | (byte & 0x7F)
        pos += 1
    return offset, pos


def decompress_at(data, pos):
    """Decompress a zlib stream starting at pos.

    Returns (decompressed_bytes, number_of_compressed_bytes_consumed).
    """
    dobj = zlib.decompressobj()
    result = dobj.decompress(data[pos:])
    consumed = len(data) - pos - len(dobj.unused_data)
    return result, consumed


def apply_delta(base_data, delta_data):
    """Apply binary delta instructions to reconstruct a target object.

    Delta format: source_size varint, target_size varint, then instructions.
    Instructions: MSB=1 is COPY (remaining bits select offset/size bytes),
    MSB=0 and value>0 is INSERT of that many literal bytes.
    """
    pos = 0

    # Read source size varint
    source_size = 0
    shift = 0
    while True:
        byte = delta_data[pos]
        source_size |= (byte & 0x7F) << shift
        shift += 7
        pos += 1
        if not (byte & 0x80):
            break

    # Read target size varint
    target_size = 0
    shift = 0
    while True:
        byte = delta_data[pos]
        target_size |= (byte & 0x7F) << shift
        shift += 7
        pos += 1
        if not (byte & 0x80):
            break

    if len(base_data) != source_size:
        raise ValueError(
            f"Delta source size mismatch: base has {len(base_data)} bytes, "
            f"delta header says {source_size}"
        )

    result = bytearray()
    while pos < len(delta_data):
        cmd = delta_data[pos]
        pos += 1

        if cmd & 0x80:
            # COPY instruction: remaining bits select which offset/size
            # bytes follow. Bits 0-3 -> offset bytes 0-3,
            # bits 4-6 -> size bytes 0-2. Missing bytes default to 0.
            offset = 0
            size = 0
            if cmd & 0x01:
                offset = delta_data[pos]; pos += 1
            if cmd & 0x02:
                offset |= delta_data[pos] << 8; pos += 1
            if cmd & 0x04:
                offset |= delta_data[pos] << 16; pos += 1
            if cmd & 0x08:
                offset |= delta_data[pos] << 24; pos += 1
            if cmd & 0x10:
                size = delta_data[pos]; pos += 1
            if cmd & 0x20:
                size |= delta_data[pos] << 8; pos += 1
            if cmd & 0x40:
                size |= delta_data[pos] << 16; pos += 1
            if size == 0:
                size = 0x10000
            result.extend(base_data[offset:offset + size])

        elif cmd > 0:
            # INSERT instruction: next <cmd> bytes are literal data
            result.extend(delta_data[pos:pos + cmd])
            pos += cmd

        else:
            raise ValueError("Invalid delta instruction byte: 0x00")

    if len(result) != target_size:
        raise ValueError(
            f"Delta target size mismatch: produced {len(result)} bytes, "
            f"expected {target_size}"
        )

    return bytes(result)


def compute_object_sha1(type_name, data):
    """Compute the SHA1 hash for a Git object (type SP size NUL data)."""
    header = f"{type_name} {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()


class PackReader:
    """Read objects from a Git pack file, with or without a pack index.

    When no index is available, scans the pack file sequentially to
    discover all entries and build an internal SHA1-to-offset mapping.
    """

    def __init__(self, pack_path, idx_path=None):
        with open(pack_path, "rb") as f:
            self.data = f.read()

        if self.data[:4] != b"PACK":
            raise ValueError("Not a valid pack file")
        self.version = struct.unpack(">I", self.data[4:8])[0]
        if self.version != 2:
            raise ValueError(f"Unsupported pack version: {self.version}")
        self.num_objects = struct.unpack(">I", self.data[8:12])[0]

        self._cache = {}          # offset -> (type_name, data)
        self._sha1_to_offset = {} # sha1_hex -> pack_offset
        self._entries = []        # list of entry dicts from scanning
        self._offset_lookup = {}  # offset -> entry dict

        if idx_path and os.path.exists(idx_path):
            self._load_index(idx_path)
        else:
            self._scan_and_resolve()

    def _load_index(self, path):
        """Load a pack index v2 file to populate SHA1-to-offset mapping."""
        with open(path, "rb") as f:
            idx_data = f.read()

        magic = idx_data[:4]
        version = struct.unpack(">I", idx_data[4:8])[0]
        if magic != b"\xfftOc" or version != 2:
            raise ValueError(
                f"Unsupported index: magic={magic!r}, version={version}"
            )

        num_objects = struct.unpack(
            ">I", idx_data[8 + 255 * 4:8 + 256 * 4]
        )[0]

        sha1_start = 8 + 256 * 4
        crc32_start = sha1_start + num_objects * 20
        offset_start = crc32_start + num_objects * 4
        large_offset_start = offset_start + num_objects * 4

        for i in range(num_objects):
            sha1 = idx_data[
                sha1_start + i * 20:sha1_start + (i + 1) * 20
            ].hex()
            raw_off = struct.unpack(
                ">I",
                idx_data[offset_start + i * 4:offset_start + (i + 1) * 4],
            )[0]
            if raw_off & 0x80000000:
                large_idx = raw_off & 0x7FFFFFFF
                raw_off = struct.unpack(
                    ">Q",
                    idx_data[
                        large_offset_start + large_idx * 8:
                        large_offset_start + (large_idx + 1) * 8
                    ],
                )[0]
            self._sha1_to_offset[sha1] = raw_off

    def _scan_and_resolve(self):
        """Scan the pack file sequentially and resolve all objects."""
        self._scan_entries()
        self._resolve_all()

    def _scan_entries(self):
        """First pass: scan all pack entries to record positions and data."""
        pos = 12  # Skip PACK header (4 magic + 4 version + 4 num_objects)

        for _ in range(self.num_objects):
            entry_start = pos
            obj_type, _size, data_pos = read_size_type(self.data, pos)

            neg_offset = None
            ref_sha1 = None

            if obj_type == OBJ_OFS_DELTA:
                neg_offset, data_pos = read_ofs_offset(self.data, data_pos)
            elif obj_type == OBJ_REF_DELTA:
                ref_sha1 = self.data[data_pos:data_pos + 20].hex()
                data_pos += 20

            decompressed, consumed = decompress_at(self.data, data_pos)
            raw_end = data_pos + consumed

            self._entries.append({
                "offset": entry_start,
                "raw_end": raw_end,
                "type_code": obj_type,
                "decompressed": decompressed,
                "neg_offset": neg_offset,
                "ref_sha1": ref_sha1,
            })

            pos = raw_end

        self._offset_lookup = {e["offset"]: e for e in self._entries}

    def _resolve_all(self):
        """Second pass: resolve all objects and compute SHA1s.

        Resolves non-delta objects first, then OFS_DELTA (which reference
        bases by offset), then REF_DELTA (which reference bases by SHA1).
        Multiple passes handle deep chains.
        """
        # Phase 1: non-delta objects
        for entry in self._entries:
            if entry["type_code"] in TYPE_NAMES:
                type_name = TYPE_NAMES[entry["type_code"]]
                self._cache[entry["offset"]] = (type_name, entry["decompressed"])
                sha1 = compute_object_sha1(type_name, entry["decompressed"])
                self._sha1_to_offset[sha1] = entry["offset"]

        # Phase 2: delta objects (may need multiple passes for chains)
        remaining = [
            e for e in self._entries if e["type_code"] not in TYPE_NAMES
        ]
        max_passes = 20
        for _ in range(max_passes):
            if not remaining:
                break
            still_remaining = []
            for entry in remaining:
                try:
                    type_name, obj_data = self._resolve_entry(entry)
                    sha1 = compute_object_sha1(type_name, obj_data)
                    self._sha1_to_offset[sha1] = entry["offset"]
                except KeyError:
                    still_remaining.append(entry)
            if len(still_remaining) == len(remaining):
                # No progress — unresolvable entries
                break
            remaining = still_remaining

        if remaining:
            raise ValueError(
                f"Could not resolve {len(remaining)} delta object(s)"
            )

    def _resolve_entry(self, entry):
        """Resolve a scanned entry to its final (type_name, data)."""
        offset = entry["offset"]
        if offset in self._cache:
            return self._cache[offset]

        if entry["type_code"] in TYPE_NAMES:
            result = (TYPE_NAMES[entry["type_code"]], entry["decompressed"])

        elif entry["type_code"] == OBJ_OFS_DELTA:
            base_offset = offset - entry["neg_offset"]
            if base_offset not in self._offset_lookup:
                raise KeyError(f"OFS_DELTA base at offset {base_offset} not found")
            base_entry = self._offset_lookup[base_offset]
            base_type, base_data = self._resolve_entry(base_entry)
            result_data = apply_delta(base_data, entry["decompressed"])
            result = (base_type, result_data)

        elif entry["type_code"] == OBJ_REF_DELTA:
            base_sha1 = entry["ref_sha1"]
            base_offset = self._sha1_to_offset.get(base_sha1)
            if base_offset is None:
                raise KeyError(f"REF_DELTA base {base_sha1} not found")
            base_entry = self._offset_lookup[base_offset]
            base_type, base_data = self._resolve_entry(base_entry)
            result_data = apply_delta(base_data, entry["decompressed"])
            result = (base_type, result_data)

        else:
            raise ValueError(f"Unknown object type code: {entry['type_code']}")

        self._cache[offset] = result
        return result

    def _read_at_offset(self, offset):
        """Read and resolve an object at a given pack offset (index mode)."""
        if offset in self._cache:
            return self._cache[offset]

        obj_type, _size, data_pos = read_size_type(self.data, offset)

        if obj_type == OBJ_OFS_DELTA:
            neg_offset, data_pos = read_ofs_offset(self.data, data_pos)
            delta_data, _ = decompress_at(self.data, data_pos)
            base_offset = offset - neg_offset
            base_type, base_data = self._read_at_offset(base_offset)
            result_data = apply_delta(base_data, delta_data)
            result = (base_type, result_data)

        elif obj_type == OBJ_REF_DELTA:
            ref_sha1 = self.data[data_pos:data_pos + 20].hex()
            data_pos += 20
            delta_data, _ = decompress_at(self.data, data_pos)
            base_offset = self._sha1_to_offset.get(ref_sha1)
            if base_offset is None:
                raise KeyError(f"REF_DELTA base {ref_sha1} not found")
            base_type, base_data = self._read_at_offset(base_offset)
            result_data = apply_delta(base_data, delta_data)
            result = (base_type, result_data)

        elif obj_type in TYPE_NAMES:
            data, _ = decompress_at(self.data, data_pos)
            result = (TYPE_NAMES[obj_type], data)

        else:
            raise ValueError(f"Unknown object type code: {obj_type}")

        self._cache[offset] = result
        return result

    def read_object(self, sha1):
        """Read an object by its SHA1 hex string."""
        offset = self._sha1_to_offset.get(sha1)
        if offset is None:
            raise KeyError(f"Object {sha1} not found in pack")

        if offset in self._cache:
            return self._cache[offset]

        return self._read_at_offset(offset)

    def all_sha1s(self):
        """Return list of all SHA1 hex strings in this pack."""
        return list(self._sha1_to_offset.keys())

    def rebuild_index(self, idx_path):
        """Generate a valid pack index v2 file from the pack data alone.

        The v2 index format consists of:
          - 4-byte magic (\\xff\\x74\\x4f\\x63) + 4-byte version (2)
          - 256-entry fanout table (cumulative counts by first SHA1 byte)
          - Sorted SHA1 table (N * 20 bytes)
          - CRC32 table (N * 4 bytes, CRC32 of raw pack entry bytes)
          - Offset table (N * 4 bytes, with large-offset indirection if needed)
          - Large offset table (if any offset >= 2^31)
          - 20-byte pack file checksum
          - 20-byte index checksum (SHA1 of all preceding index data)
        """
        # Ensure we have scanned the pack
        if not self._entries:
            self._scan_entries()
            self._resolve_all()

        # Collect (sha1_bytes, offset, crc32) for each entry
        index_entries = []
        for entry in self._entries:
            type_name, obj_data = self._resolve_entry(entry)
            sha1_hex = compute_object_sha1(type_name, obj_data)
            sha1_bytes = bytes.fromhex(sha1_hex)

            # CRC32 of the raw pack entry bytes
            raw_bytes = self.data[entry["offset"]:entry["raw_end"]]
            crc = binascii.crc32(raw_bytes) & 0xFFFFFFFF

            index_entries.append((sha1_bytes, entry["offset"], crc))

        # Sort by SHA1
        index_entries.sort(key=lambda x: x[0])

        # Build the binary index
        buf = bytearray()

        # Header: magic + version
        buf.extend(b"\xfftOc")
        buf.extend(struct.pack(">I", 2))

        # Fanout table: 256 entries, each is cumulative count of objects
        # whose first SHA1 byte <= index
        fanout = [0] * 256
        for sha1_bytes, _, _ in index_entries:
            fanout[sha1_bytes[0]] += 1
        for i in range(1, 256):
            fanout[i] += fanout[i - 1]
        for count in fanout:
            buf.extend(struct.pack(">I", count))

        # SHA1 table
        for sha1_bytes, _, _ in index_entries:
            buf.extend(sha1_bytes)

        # CRC32 table
        for _, _, crc in index_entries:
            buf.extend(struct.pack(">I", crc))

        # Offset table (with large offset indirection if needed)
        large_offsets = []
        for _, offset, _ in index_entries:
            if offset >= 0x80000000:
                large_idx = len(large_offsets)
                buf.extend(struct.pack(">I", 0x80000000 | large_idx))
                large_offsets.append(offset)
            else:
                buf.extend(struct.pack(">I", offset))

        # Large offset table
        for off in large_offsets:
            buf.extend(struct.pack(">Q", off))

        # Pack file checksum (last 20 bytes of the .pack file)
        pack_checksum = self.data[-20:]
        buf.extend(pack_checksum)

        # Index checksum (SHA1 of everything written so far)
        idx_checksum = hashlib.sha1(bytes(buf)).digest()
        buf.extend(idx_checksum)

        with open(idx_path, "wb") as f:
            f.write(bytes(buf))


def format_tree(data):
    """Pretty-print a binary tree object to match `git cat-file -p` output.

    Binary tree entry: <mode-ascii> SP <name-bytes> NUL <20-byte-sha1>
    Output per entry:  <mode-padded> SP <type> SP <sha1-hex> TAB <name> LF
    """
    lines = []
    pos = 0
    while pos < len(data):
        space_idx = data.index(b" ", pos)
        mode = data[pos:space_idx].decode("ascii")

        null_idx = data.index(b"\x00", space_idx + 1)
        name = data[space_idx + 1:null_idx].decode("utf-8", errors="replace")

        sha1_hex = data[null_idx + 1:null_idx + 21].hex()
        pos = null_idx + 21

        # Determine type from mode
        if mode == "40000":
            obj_type = "tree"
            mode = "040000"
        elif mode == "160000":
            obj_type = "commit"
        else:
            obj_type = "blob"

        lines.append(f"{mode} {obj_type} {sha1_hex}\t{name}")

    return "\n".join(lines) + "\n" if lines else ""


def main():
    if len(sys.argv) < 3:
        print(
            f"Usage: {sys.argv[0]} <git-dir> <-t|-p> <sha1>",
            file=sys.stderr,
        )
        print(
            f"       {sys.argv[0]} <git-dir> --rebuild-index",
            file=sys.stderr,
        )
        sys.exit(1)

    git_dir = sys.argv[1]
    mode = sys.argv[2]

    # Locate pack files
    pack_dir = os.path.join(git_dir, "objects", "pack")
    if not os.path.isdir(pack_dir):
        print(f"Pack directory not found: {pack_dir}", file=sys.stderr)
        sys.exit(1)

    pack_files = sorted(f for f in os.listdir(pack_dir) if f.endswith(".pack"))
    if not pack_files:
        print("No pack files found", file=sys.stderr)
        sys.exit(1)

    if mode == "--rebuild-index":
        for pack_name in pack_files:
            pack_path = os.path.join(pack_dir, pack_name)
            idx_name = pack_name[:-5] + ".idx"
            idx_path = os.path.join(pack_dir, idx_name)

            reader = PackReader(pack_path)
            reader.rebuild_index(idx_path)
            print(f"Index rebuilt: {idx_path}")
        return

    if len(sys.argv) != 4:
        print(
            f"Usage: {sys.argv[0]} <git-dir> <-t|-p> <sha1>",
            file=sys.stderr,
        )
        sys.exit(1)

    sha1 = sys.argv[3]

    for pack_name in pack_files:
        pack_path = os.path.join(pack_dir, pack_name)

        # Try to find a matching .idx file
        idx_name = pack_name[:-5] + ".idx"
        idx_candidate = os.path.join(pack_dir, idx_name)
        idx_path = idx_candidate if os.path.exists(idx_candidate) else None

        reader = PackReader(pack_path, idx_path)

        if sha1 not in reader.all_sha1s():
            continue

        obj_type, data = reader.read_object(sha1)

        if mode == "-t":
            print(obj_type)
        elif mode == "-p":
            if obj_type == "tree":
                sys.stdout.buffer.write(format_tree(data).encode("utf-8"))
            else:
                sys.stdout.buffer.write(data)
        return

    # Object not found in any pack
    print(f"Object {sha1} not found", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
