#!/usr/bin/env python3
"""
Rebuild a Git packfile index (.idx v2) from the raw .pack file.

Parses the binary packfile format directly, resolves delta-compressed objects
(OFS_DELTA and REF_DELTA), computes SHA-1 hashes, and generates a valid
version-2 .idx file.

"""

import hashlib
import struct
import sys
import zlib
from pathlib import Path

# Git packfile object type constants
OBJ_COMMIT = 1
OBJ_TREE = 2
OBJ_BLOB = 3
OBJ_TAG = 4
OBJ_OFS_DELTA = 6
OBJ_REF_DELTA = 7

TYPE_NAMES = {
    OBJ_COMMIT: b"commit",
    OBJ_TREE: b"tree",
    OBJ_BLOB: b"blob",
    OBJ_TAG: b"tag",
}


class PackfileParser:
    """Parses a Git packfile and resolves all objects including deltas."""

    def __init__(self, pack_path):
        with open(pack_path, "rb") as f:
            self.data = f.read()
        self.entries = []
        self._resolved = {}

    def parse(self):
        """Parse the packfile and return (object_info_list, pack_sha1)."""
        # Validate and read header
        assert self.data[:4] == b"PACK", "Invalid packfile signature"
        version = struct.unpack(">I", self.data[4:8])[0]
        assert version == 2, f"Unsupported pack version: {version}"
        num_objects = struct.unpack(">I", self.data[8:12])[0]

        # Parse all object entries
        offset = 12
        for _ in range(num_objects):
            entry = self._parse_entry(offset)
            self.entries.append(entry)
            offset = entry["end"]

        # Build offset-to-index map for OFS_DELTA resolution
        self._offset_map = {e["offset"]: i for i, e in enumerate(self.entries)}

        # Resolve every object and compute its SHA-1
        results = []
        for i, entry in enumerate(self.entries):
            obj_type, obj_data = self._resolve(i)
            sha1 = self._git_sha1(obj_type, obj_data)
            results.append(
                {
                    "sha1": sha1,
                    "offset": entry["offset"],
                    "crc32": entry["crc32"],
                }
            )

        # Pack trailer is the SHA-1 of all preceding content
        pack_sha1 = self.data[-20:]
        return results, pack_sha1

    def _parse_entry(self, offset):
        """Parse one object entry starting at `offset`."""
        entry_start = offset

        # Variable-length type+size header
        byte = self.data[offset]
        obj_type = (byte >> 4) & 0x07
        size = byte & 0x0F
        shift = 4
        offset += 1
        while byte & 0x80:
            byte = self.data[offset]
            size |= (byte & 0x7F) << shift
            shift += 7
            offset += 1

        entry = {"offset": entry_start, "type": obj_type, "size": size}

        # Delta-specific headers
        if obj_type == OBJ_OFS_DELTA:
            byte = self.data[offset]
            neg_offset = byte & 0x7F
            offset += 1
            while byte & 0x80:
                byte = self.data[offset]
                neg_offset = ((neg_offset + 1) << 7) | (byte & 0x7F)
                offset += 1
            entry["base_offset"] = entry_start - neg_offset

        elif obj_type == OBJ_REF_DELTA:
            entry["base_sha1"] = self.data[offset : offset + 20]
            offset += 20

        # Decompress the zlib-compressed object data
        dec = zlib.decompressobj()
        decompressed = dec.decompress(self.data[offset:])
        consumed = len(self.data[offset:]) - len(dec.unused_data)
        offset += consumed

        entry["data"] = decompressed
        entry["end"] = offset
        entry["crc32"] = zlib.crc32(self.data[entry_start:offset]) & 0xFFFFFFFF

        return entry

    def _resolve(self, idx):
        """Resolve entry at `idx` to (base_type, full_data), following delta chains."""
        if idx in self._resolved:
            return self._resolved[idx]

        entry = self.entries[idx]
        obj_type = entry["type"]

        if obj_type in TYPE_NAMES:
            result = (obj_type, entry["data"])

        elif obj_type == OBJ_OFS_DELTA:
            base_idx = self._offset_map[entry["base_offset"]]
            base_type, base_data = self._resolve(base_idx)
            result = (base_type, self._apply_delta(base_data, entry["data"]))

        elif obj_type == OBJ_REF_DELTA:
            target = entry["base_sha1"]
            base_idx = self._find_by_sha1(target)
            base_type, base_data = self._resolve(base_idx)
            result = (base_type, self._apply_delta(base_data, entry["data"]))

        else:
            raise ValueError(f"Unknown object type {obj_type}")

        self._resolved[idx] = result
        return result

    def _find_by_sha1(self, target_sha1):
        """Find an entry index by computing SHA-1 of resolved objects."""
        for i in range(len(self.entries)):
            obj_type, obj_data = self._resolve(i)
            if self._git_sha1(obj_type, obj_data) == target_sha1:
                return i
        raise ValueError(f"Base object {target_sha1.hex()} not found in pack")

    def _apply_delta(self, base, delta):
        """Apply delta instructions (copy/insert) to reconstruct target data."""
        off = 0

        # Read source (base) size as variable-length int
        src_size, off = self._read_varint(delta, off)
        assert len(base) == src_size, (
            f"Base size mismatch: expected {src_size}, got {len(base)}"
        )

        # Read target size
        tgt_size, off = self._read_varint(delta, off)

        result = bytearray()

        while off < len(delta):
            cmd = delta[off]
            off += 1

            if cmd & 0x80:
                # COPY instruction: copy bytes from the base object
                copy_off = 0
                copy_len = 0

                if cmd & 0x01:
                    copy_off |= delta[off]
                    off += 1
                if cmd & 0x02:
                    copy_off |= delta[off] << 8
                    off += 1
                if cmd & 0x04:
                    copy_off |= delta[off] << 16
                    off += 1
                if cmd & 0x08:
                    copy_off |= delta[off] << 24
                    off += 1
                if cmd & 0x10:
                    copy_len |= delta[off]
                    off += 1
                if cmd & 0x20:
                    copy_len |= delta[off] << 8
                    off += 1
                if cmd & 0x40:
                    copy_len |= delta[off] << 16
                    off += 1

                if copy_len == 0:
                    copy_len = 0x10000

                result.extend(base[copy_off : copy_off + copy_len])

            elif cmd > 0:
                # INSERT instruction: next `cmd` bytes are literal data
                result.extend(delta[off : off + cmd])
                off += cmd

            else:
                raise ValueError("Invalid delta opcode: 0x00 is reserved")

        assert len(result) == tgt_size, (
            f"Target size mismatch: expected {tgt_size}, got {len(result)}"
        )
        return bytes(result)

    @staticmethod
    def _read_varint(data, offset):
        """Read a variable-length integer (used in delta size headers)."""
        value = 0
        shift = 0
        while True:
            byte = data[offset]
            offset += 1
            value |= (byte & 0x7F) << shift
            shift += 7
            if not (byte & 0x80):
                break
        return value, offset

    @staticmethod
    def _git_sha1(obj_type, data):
        """Compute the SHA-1 hash of a Git object (type + space + size + NUL + data)."""
        type_name = TYPE_NAMES[obj_type]
        header = type_name + b" " + str(len(data)).encode("ascii") + b"\0"
        return hashlib.sha1(header + data).digest()


def write_idx_v2(idx_path, objects, pack_sha1):
    """Generate a Git packfile index file in version 2 format."""
    # Sort by SHA-1 (required by the format)
    objects.sort(key=lambda o: o["sha1"])

    buf = bytearray()

    # Header: magic number + version
    buf.extend(b"\xfftOc")
    buf.extend(struct.pack(">I", 2))

    # Fanout table: 256 cumulative counts
    for i in range(256):
        count = 0
        for o in objects:
            if o["sha1"][0] <= i:
                count += 1
        buf.extend(struct.pack(">I", count))

    # Sorted SHA-1 hashes (20 bytes each)
    for obj in objects:
        buf.extend(obj["sha1"])

    # CRC32 values (in same sorted order)
    for obj in objects:
        buf.extend(struct.pack(">I", obj["crc32"]))

    # Pack file offsets (4 bytes each; MSB set means use large offset table)
    large_offsets = []
    for obj in objects:
        if obj["offset"] >= 0x80000000:
            idx = len(large_offsets)
            large_offsets.append(obj["offset"])
            buf.extend(struct.pack(">I", 0x80000000 | idx))
        else:
            buf.extend(struct.pack(">I", obj["offset"]))

    # Large offset table (8 bytes each, only for packs > 2 GiB)
    for off in large_offsets:
        buf.extend(struct.pack(">Q", off))

    # Copy of the packfile's trailing SHA-1
    buf.extend(pack_sha1)

    # Compute and append the SHA-1 of the entire .idx content
    idx_sha1 = hashlib.sha1(buf).digest()
    buf.extend(idx_sha1)

    with open(idx_path, "wb") as f:
        f.write(buf)


def main():
    repo = Path("/app/repo")
    pack_dir = repo / ".git" / "objects" / "pack"

    pack_files = list(pack_dir.glob("*.pack"))
    if not pack_files:
        print("ERROR: No .pack file found in", pack_dir, file=sys.stderr)
        return 1

    pack_path = pack_files[0]
    idx_path = pack_path.with_suffix(".idx")

    print(f"Parsing packfile: {pack_path}")
    parser = PackfileParser(str(pack_path))
    objects, pack_sha1 = parser.parse()
    print(f"Found {len(objects)} objects")

    print(f"Writing index: {idx_path}")
    write_idx_v2(str(idx_path), objects, pack_sha1)
    print("Packfile index rebuilt successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
