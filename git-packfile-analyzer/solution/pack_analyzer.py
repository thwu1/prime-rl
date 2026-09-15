#!/usr/bin/env python3
"""
Git packfile analyzer — parse, inspect, verify, and rebuild pack-index v2
files using only Python standard library modules.
"""

import sys
import os
import io
import zlib
import hashlib
import struct
import json

# Pack object type constants
OBJ_COMMIT = 1
OBJ_TREE = 2
OBJ_BLOB = 3
OBJ_TAG = 4
OBJ_OFS_DELTA = 6
OBJ_REF_DELTA = 7

TYPE_NAMES = {
    OBJ_COMMIT: 'commit',
    OBJ_TREE: 'tree',
    OBJ_BLOB: 'blob',
    OBJ_TAG: 'tag',
    OBJ_OFS_DELTA: 'ofs_delta',
    OBJ_REF_DELTA: 'ref_delta',
}


def read_varint_type(stream):
    """Read object type and size from pack entry header.

    First byte: bit 7 = continuation, bits 6-4 = type, bits 3-0 = size[3:0]
    Subsequent bytes: bit 7 = continuation, bits 6-0 = size (shifted by 4, 11, 18, ...)
    """
    byte = stream.read(1)[0]
    obj_type = (byte >> 4) & 0x7
    size = byte & 0x0f
    shift = 4
    while byte & 0x80:
        byte = stream.read(1)[0]
        size |= (byte & 0x7f) << shift
        shift += 7
    return obj_type, size


def read_ofs_delta_offset(stream):
    """Read variable-length negative offset for OFS_DELTA objects.

    Each byte except the last has MSB set.
    Offset = ((prev + 1) << 7) | (byte & 0x7f) for continuation bytes.
    """
    byte = stream.read(1)[0]
    offset = byte & 0x7f
    while byte & 0x80:
        byte = stream.read(1)[0]
        offset = ((offset + 1) << 7) | (byte & 0x7f)
    return offset


def decompress_from_stream(stream):
    """Decompress a zlib stream, leaving the stream positioned after it."""
    decompressor = zlib.decompressobj()
    result = b''
    while True:
        chunk = stream.read(4096)
        if not chunk:
            break
        result += decompressor.decompress(chunk)
        if decompressor.eof:
            unused = len(decompressor.unused_data)
            if unused:
                stream.seek(-unused, 1)
            break
    return result


def apply_delta(base_data, delta_data):
    """Apply git binary delta instructions to produce resolved content.

    Delta format:
    - source_size (variable-length int)
    - target_size (variable-length int)
    - instructions:
        - copy (MSB set): copy from base at offset/size encoded in subsequent bytes
        - insert (MSB clear, 1-127): insert next N literal bytes
    """
    pos = 0

    def read_varint():
        nonlocal pos
        value = 0
        shift = 0
        while True:
            byte = delta_data[pos]
            pos += 1
            value |= (byte & 0x7f) << shift
            shift += 7
            if not (byte & 0x80):
                break
        return value

    source_size = read_varint()
    target_size = read_varint()

    if len(base_data) != source_size:
        raise ValueError(
            f"Delta source size mismatch: expected {source_size}, "
            f"got {len(base_data)}"
        )

    result = bytearray()

    while pos < len(delta_data):
        cmd = delta_data[pos]
        pos += 1

        if cmd & 0x80:
            # Copy instruction: copy bytes from base_data
            copy_offset = 0
            copy_size = 0
            if cmd & 0x01:
                copy_offset = delta_data[pos]; pos += 1
            if cmd & 0x02:
                copy_offset |= delta_data[pos] << 8; pos += 1
            if cmd & 0x04:
                copy_offset |= delta_data[pos] << 16; pos += 1
            if cmd & 0x08:
                copy_offset |= delta_data[pos] << 24; pos += 1
            if cmd & 0x10:
                copy_size = delta_data[pos]; pos += 1
            if cmd & 0x20:
                copy_size |= delta_data[pos] << 8; pos += 1
            if cmd & 0x40:
                copy_size |= delta_data[pos] << 16; pos += 1
            if copy_size == 0:
                copy_size = 0x10000
            result.extend(base_data[copy_offset:copy_offset + copy_size])

        elif cmd > 0:
            # Insert instruction: insert next cmd literal bytes
            result.extend(delta_data[pos:pos + cmd])
            pos += cmd

        else:
            raise ValueError("Invalid delta instruction: 0x00")

    if len(result) != target_size:
        raise ValueError(
            f"Delta target size mismatch: expected {target_size}, "
            f"got {len(result)}"
        )

    return bytes(result)


def git_object_sha1(type_name, data):
    """Compute the SHA-1 hash of a git object: '<type> <size>\\0<data>'."""
    header = f"{type_name} {len(data)}\0".encode('ascii')
    return hashlib.sha1(header + data).hexdigest()


class PackfileParser:
    """Full parser for git packfile format v2/v3."""

    def __init__(self, pack_path):
        self.pack_path = pack_path
        with open(pack_path, 'rb') as f:
            self.pack_data = f.read()
        self.objects = []
        self.version = None
        self.num_objects = None
        self._parsed = False

    def parse(self):
        if self._parsed:
            return
        stream = io.BytesIO(self.pack_data)

        # 12-byte header: 'PACK' + version (4 bytes) + object count (4 bytes)
        magic = stream.read(4)
        if magic != b'PACK':
            raise ValueError(f"Invalid pack magic: {magic!r}")
        self.version = struct.unpack('>I', stream.read(4))[0]
        if self.version not in (2, 3):
            raise ValueError(f"Unsupported pack version: {self.version}")
        self.num_objects = struct.unpack('>I', stream.read(4))[0]

        for _ in range(self.num_objects):
            entry_start = stream.tell()
            obj_type, declared_size = read_varint_type(stream)

            base_ref = None
            if obj_type == OBJ_OFS_DELTA:
                neg_offset = read_ofs_delta_offset(stream)
                base_ref = ('ofs', entry_start - neg_offset)
            elif obj_type == OBJ_REF_DELTA:
                base_ref = ('ref', stream.read(20).hex())

            data = decompress_from_stream(stream)
            entry_end = stream.tell()

            crc = zlib.crc32(self.pack_data[entry_start:entry_end]) & 0xffffffff

            self.objects.append({
                'offset': entry_start,
                'entry_end': entry_end,
                'pack_type': obj_type,
                'declared_size': declared_size,
                'data': data,
                'base_ref': base_ref,
                'crc32': crc,
            })

        self._parsed = True
        self._resolve_deltas()

    def _resolve_deltas(self):
        """Resolve all delta objects to their actual types and content."""
        offset_map = {obj['offset']: i for i, obj in enumerate(self.objects)}
        sha_map = {}

        def resolve(idx, depth=0):
            if depth > 200:
                raise ValueError("Delta chain exceeds maximum depth")
            obj = self.objects[idx]
            if 'resolved_type' in obj:
                return

            if obj['pack_type'] not in (OBJ_OFS_DELTA, OBJ_REF_DELTA):
                obj['resolved_type'] = obj['pack_type']
                obj['resolved_data'] = obj['data']
                type_name = TYPE_NAMES[obj['resolved_type']]
                obj['sha1'] = git_object_sha1(type_name, obj['resolved_data'])
                sha_map[obj['sha1']] = idx
                return

            # Locate and resolve the base object first
            if obj['base_ref'][0] == 'ofs':
                base_offset = obj['base_ref'][1]
                if base_offset not in offset_map:
                    raise ValueError(
                        f"OFS_DELTA base not found at offset {base_offset}"
                    )
                base_idx = offset_map[base_offset]
            else:
                # REF_DELTA: base referenced by SHA-1
                base_sha = obj['base_ref'][1]
                # Ensure all non-delta objects are resolved so sha_map is populated
                for j, o in enumerate(self.objects):
                    if (o['pack_type'] not in (OBJ_OFS_DELTA, OBJ_REF_DELTA)
                            and 'sha1' not in o):
                        resolve(j, depth + 1)
                if base_sha not in sha_map:
                    # Some deltas might resolve to produce the needed base
                    for j in range(len(self.objects)):
                        if j != idx and 'resolved_type' not in self.objects[j]:
                            resolve(j, depth + 1)
                            if base_sha in sha_map:
                                break
                if base_sha not in sha_map:
                    raise ValueError(
                        f"REF_DELTA base {base_sha} not found in pack"
                    )
                base_idx = sha_map[base_sha]

            resolve(base_idx, depth + 1)
            base_obj = self.objects[base_idx]

            resolved_data = apply_delta(
                base_obj['resolved_data'], obj['data']
            )
            obj['resolved_type'] = base_obj['resolved_type']
            obj['resolved_data'] = resolved_data
            type_name = TYPE_NAMES[obj['resolved_type']]
            obj['sha1'] = git_object_sha1(type_name, obj['resolved_data'])
            sha_map[obj['sha1']] = idx

        for i in range(len(self.objects)):
            resolve(i)

    def list_objects(self):
        """Return list of all objects with metadata."""
        self.parse()
        result = []
        for obj in self.objects:
            entry = {
                'sha1': obj['sha1'],
                'type': TYPE_NAMES[obj['resolved_type']],
                'size': len(obj['resolved_data']),
                'offset': obj['offset'],
                'pack_type': TYPE_NAMES[obj['pack_type']],
            }
            result.append(entry)
        result.sort(key=lambda x: x['offset'])
        return result

    def extract_object(self, sha1):
        """Return (type_name, raw_data) for the object with given SHA-1."""
        self.parse()
        for obj in self.objects:
            if obj['sha1'] == sha1:
                return TYPE_NAMES[obj['resolved_type']], obj['resolved_data']
        return None, None

    def verify_checksum(self):
        """Verify the trailing 20-byte SHA-1 checksum of the packfile."""
        stored = self.pack_data[-20:]
        computed = hashlib.sha1(self.pack_data[:-20]).digest()
        return stored == computed, stored.hex(), computed.hex()

    def build_index(self, idx_path=None):
        """Generate a pack-index v2 file adjacent to the packfile."""
        self.parse()

        if idx_path is None:
            idx_path = self.pack_path.rsplit('.', 1)[0] + '.idx'

        # Sort objects by SHA-1 (as raw bytes for correct ordering)
        sorted_objs = sorted(
            self.objects, key=lambda o: bytes.fromhex(o['sha1'])
        )
        sha1_bytes_list = [
            bytes.fromhex(o['sha1']) for o in sorted_objs
        ]

        # Pack checksum = last 20 bytes of pack file
        pack_checksum = self.pack_data[-20:]

        buf = bytearray()

        # Header: magic number + version
        buf.extend(b'\xfftOc')          # pack-index v2 magic
        buf.extend(struct.pack('>I', 2))  # version 2

        # Fan-out table: 256 4-byte entries
        # fanout[i] = number of objects with first SHA-1 byte <= i
        for i in range(256):
            count = sum(1 for s in sha1_bytes_list if s[0] <= i)
            buf.extend(struct.pack('>I', count))

        # SHA-1 table (sorted)
        for sha_bytes in sha1_bytes_list:
            buf.extend(sha_bytes)

        # CRC32 table (in same sorted order)
        for obj in sorted_objs:
            buf.extend(struct.pack('>I', obj['crc32']))

        # 4-byte offset table
        large_offsets = []
        for obj in sorted_objs:
            offset = obj['offset']
            if offset >= 0x80000000:
                buf.extend(
                    struct.pack('>I', 0x80000000 | len(large_offsets))
                )
                large_offsets.append(offset)
            else:
                buf.extend(struct.pack('>I', offset))

        # 8-byte large offset table (only if any offset >= 2 GiB)
        for offset in large_offsets:
            buf.extend(struct.pack('>Q', offset))

        # Trailing pack checksum
        buf.extend(pack_checksum)

        # Trailing index checksum (SHA-1 of everything above)
        idx_checksum = hashlib.sha1(bytes(buf)).digest()
        buf.extend(idx_checksum)

        with open(idx_path, 'wb') as f:
            f.write(buf)

        return idx_path


def cmd_list(pack_path):
    parser = PackfileParser(pack_path)
    objects = parser.list_objects()
    print(json.dumps(objects, indent=2))


def cmd_extract(pack_path, sha1):
    parser = PackfileParser(pack_path)
    obj_type, data = parser.extract_object(sha1)
    if data is None:
        print(f"Object {sha1} not found", file=sys.stderr)
        sys.exit(1)
    sys.stdout.buffer.write(data)


def cmd_verify(pack_path):
    parser = PackfileParser(pack_path)
    ok, stored, computed = parser.verify_checksum()
    if ok:
        print(json.dumps({"valid": True, "checksum": stored}))
    else:
        print(json.dumps({
            "valid": False,
            "stored": stored,
            "computed": computed,
        }))
        sys.exit(1)


def cmd_build_index(pack_path):
    parser = PackfileParser(pack_path)
    idx_path = parser.build_index()
    objects = parser.list_objects()
    print(json.dumps({
        "index_path": idx_path,
        "num_objects": len(objects),
    }))


def main():
    if len(sys.argv) < 3:
        print(
            "Usage: pack_analyzer.py <command> <packfile> [args...]\n"
            "Commands:\n"
            "  list              List all objects as JSON\n"
            "  extract <sha1>    Extract object content to stdout\n"
            "  verify            Verify packfile checksum\n"
            "  build-index       Generate pack-index v2 file",
            file=sys.stderr
        )
        sys.exit(1)

    command = sys.argv[1]
    pack_path = sys.argv[2]

    if command == 'list':
        cmd_list(pack_path)
    elif command == 'extract':
        if len(sys.argv) < 4:
            print(
                "Usage: pack_analyzer.py extract <packfile> <sha1>",
                file=sys.stderr
            )
            sys.exit(1)
        cmd_extract(pack_path, sys.argv[3])
    elif command == 'verify':
        cmd_verify(pack_path)
    elif command == 'build-index':
        cmd_build_index(pack_path)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
