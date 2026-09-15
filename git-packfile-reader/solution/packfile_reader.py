
"""
Git packfile reader — adds packfile support to gitlib.py.

Implements:
  - Pack index (.idx v2) parsing with fanout table and binary search
  - Pack data (.pack) reading with variable-length object headers
  - OFS_DELTA (type 6) resolution via negative offset to base object
  - REF_DELTA (type 7) resolution via base object SHA-1 lookup
  - Delta instruction application (copy and insert operations)
"""

import struct
import zlib
import os


# ---------------------------------------------------------------------------
# Variable-length integer helpers
# ---------------------------------------------------------------------------

def _read_size_encoding(data, offset):
    """Read a variable-length size used in delta headers.

    Each byte contributes 7 bits; MSB signals continuation.
    Returns (value, new_offset).
    """
    result = 0
    shift = 0
    while True:
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if not (byte & 0x80):
            break
    return result, offset


def _read_pack_object_header(data, offset):
    """Read the type (3 bits) and uncompressed size from a pack entry header.

    First byte: MSB=continuation, bits 6-4=type, bits 3-0=size[3:0].
    Subsequent bytes: MSB=continuation, bits 6-0=size[next 7 bits].
    Returns (type_num, size, new_offset).
    """
    byte = data[offset]
    offset += 1
    type_num = (byte >> 4) & 0x07
    size = byte & 0x0F
    shift = 4
    while byte & 0x80:
        byte = data[offset]
        offset += 1
        size |= (byte & 0x7F) << shift
        shift += 7
    return type_num, size, offset


def _read_ofs_delta_offset(data, offset):
    """Read the negative offset for an OFS_DELTA entry.

    First byte contributes bits 6-0 directly.  Each subsequent byte
    (while MSB is set) shifts the previous value left by 7, adds 1
    (to encode the "n bytes back" distance), and ORs in bits 6-0.
    Returns (negative_offset, new_offset).
    """
    byte = data[offset]
    offset += 1
    result = byte & 0x7F
    while byte & 0x80:
        byte = data[offset]
        offset += 1
        result = ((result + 1) << 7) | (byte & 0x7F)
    return result, offset


# ---------------------------------------------------------------------------
# Zlib decompression at an arbitrary offset inside a buffer
# ---------------------------------------------------------------------------

def _decompress_at(data, offset):
    """Decompress zlib data starting at *offset*.

    Returns (decompressed_bytes, compressed_length_consumed).
    """
    dc = zlib.decompressobj()
    decompressed = dc.decompress(data[offset:])
    consumed = len(data) - offset - len(dc.unused_data)
    return decompressed, consumed


# ---------------------------------------------------------------------------
# Delta instruction application
# ---------------------------------------------------------------------------

def _apply_delta(base_data, delta_data):
    """Apply a delta instruction stream to *base_data*.

    Delta format
    ~~~~~~~~~~~~
    Header:
      - source_size  (variable-length int — must equal len(base_data))
      - target_size  (variable-length int — size of output)

    Then a sequence of instructions until the delta stream is exhausted:

    COPY  (MSB of instruction byte == 1):
      Bits 0-3 of the instruction byte indicate which of the next 1-4
      bytes encode the copy *offset* (little-endian).
      Bits 4-6 indicate which of the next 1-3 bytes encode the copy
      *size* (little-endian).  A size of 0 means 0x10000.
      Copy *size* bytes from *base_data* starting at *offset*.

    INSERT (MSB == 0):
      Lower 7 bits give the number of bytes to read literally from the
      delta stream and append to the output.  A zero byte is reserved.
    """
    pos = 0

    source_size, pos = _read_size_encoding(delta_data, pos)
    target_size, pos = _read_size_encoding(delta_data, pos)

    if len(base_data) != source_size:
        raise Exception(
            f"Delta source size mismatch: expected {source_size}, "
            f"got {len(base_data)}"
        )

    result = bytearray()

    while pos < len(delta_data):
        instruction = delta_data[pos]
        pos += 1

        if instruction & 0x80:
            # ---- COPY from base ----
            copy_offset = 0
            copy_size = 0

            if instruction & 0x01:
                copy_offset = delta_data[pos]; pos += 1
            if instruction & 0x02:
                copy_offset |= delta_data[pos] << 8; pos += 1
            if instruction & 0x04:
                copy_offset |= delta_data[pos] << 16; pos += 1
            if instruction & 0x08:
                copy_offset |= delta_data[pos] << 24; pos += 1

            if instruction & 0x10:
                copy_size = delta_data[pos]; pos += 1
            if instruction & 0x20:
                copy_size |= delta_data[pos] << 8; pos += 1
            if instruction & 0x40:
                copy_size |= delta_data[pos] << 16; pos += 1

            if copy_size == 0:
                copy_size = 0x10000

            result.extend(base_data[copy_offset:copy_offset + copy_size])

        elif instruction != 0:
            # ---- INSERT literal bytes ----
            result.extend(delta_data[pos:pos + instruction])
            pos += instruction

        else:
            raise Exception("Unexpected zero instruction byte in delta stream")

    if len(result) != target_size:
        raise Exception(
            f"Delta target size mismatch: expected {target_size}, "
            f"got {len(result)}"
        )

    return bytes(result)


# ---------------------------------------------------------------------------
# Pack index (.idx v2)
# ---------------------------------------------------------------------------

class PackIndex:
    """Parsed representation of a v2 pack index file."""

    def __init__(self, idx_path):
        with open(idx_path, 'rb') as f:
            self.data = f.read()

        # Magic + version
        assert self.data[:4] == b'\xfftOc', "Bad pack index magic"
        version = struct.unpack('>I', self.data[4:8])[0]
        assert version == 2, f"Unsupported pack index version: {version}"

        # 256-entry fanout table (cumulative object counts)
        self.fanout = []
        for i in range(256):
            val = struct.unpack('>I', self.data[8 + i * 4:12 + i * 4])[0]
            self.fanout.append(val)

        self.total_objects = self.fanout[255]

        # Table offsets
        self.sha_table = 8 + 256 * 4
        self.crc_table = self.sha_table + self.total_objects * 20
        self.offset_table = self.crc_table + self.total_objects * 4
        self.large_offset_table = self.offset_table + self.total_objects * 4

    def find_object(self, sha_hex):
        """Binary-search the index for *sha_hex*.

        Returns the pack-file byte offset or ``None``.
        """
        sha_bytes = bytes.fromhex(sha_hex)
        first_byte = sha_bytes[0]

        lo = self.fanout[first_byte - 1] if first_byte > 0 else 0
        hi = self.fanout[first_byte]

        while lo < hi:
            mid = (lo + hi) // 2
            entry_start = self.sha_table + mid * 20
            entry_sha = self.data[entry_start:entry_start + 20]

            if entry_sha == sha_bytes:
                # Read 4-byte offset
                off_start = self.offset_table + mid * 4
                raw_offset = struct.unpack(
                    '>I', self.data[off_start:off_start + 4]
                )[0]

                if raw_offset & 0x80000000:
                    # Large offset — index into 8-byte table
                    large_idx = raw_offset & 0x7FFFFFFF
                    lo8 = self.large_offset_table + large_idx * 8
                    return struct.unpack('>Q', self.data[lo8:lo8 + 8])[0]
                return raw_offset

            elif entry_sha < sha_bytes:
                lo = mid + 1
            else:
                hi = mid

        return None


# ---------------------------------------------------------------------------
# Pack data (.pack)
# ---------------------------------------------------------------------------

_OBJ_TYPE_MAP = {
    1: b'commit',
    2: b'tree',
    3: b'blob',
    4: b'tag',
}


class PackFile:
    """Reads objects from a Git pack data file."""

    def __init__(self, pack_path, index):
        self.index = index
        with open(pack_path, 'rb') as f:
            self.data = f.read()

        assert self.data[:4] == b'PACK', "Bad packfile magic"
        self.version = struct.unpack('>I', self.data[4:8])[0]
        self.num_objects = struct.unpack('>I', self.data[8:12])[0]

    def read_object_at(self, offset):
        """Read and fully resolve the object at *offset*.

        Returns ``(type_bytes, raw_data)`` where *type_bytes* is one of
        ``b'commit'``, ``b'tree'``, ``b'blob'``, ``b'tag'``.
        Delta objects are recursively resolved.
        """
        type_num, _size, data_offset = _read_pack_object_header(
            self.data, offset
        )

        if type_num in _OBJ_TYPE_MAP:
            # Non-delta object — just decompress
            decompressed, _ = _decompress_at(self.data, data_offset)
            return _OBJ_TYPE_MAP[type_num], decompressed

        if type_num == 6:
            # OFS_DELTA — base object is at (offset - neg_offset)
            neg_offset, data_offset = _read_ofs_delta_offset(
                self.data, data_offset
            )
            base_offset = offset - neg_offset

            delta_data, _ = _decompress_at(self.data, data_offset)
            base_type, base_data = self.read_object_at(base_offset)
            return base_type, _apply_delta(base_data, delta_data)

        if type_num == 7:
            # REF_DELTA — base identified by 20-byte SHA-1
            base_sha = format(
                int.from_bytes(self.data[data_offset:data_offset + 20], 'big'),
                '040x',
            )
            data_offset += 20

            delta_data, _ = _decompress_at(self.data, data_offset)

            # Find base in this pack
            base_pack_offset = self.index.find_object(base_sha)
            if base_pack_offset is None:
                raise Exception(
                    f"REF_DELTA base object {base_sha} not found in pack"
                )
            base_type, base_data = self.read_object_at(base_pack_offset)
            return base_type, _apply_delta(base_data, delta_data)

        raise Exception(f"Unknown pack object type number: {type_num}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_and_read_from_packs(repo, sha):
    """Search all packfiles in *repo* for object *sha*.

    Returns a ``gitlib.GitObject`` subclass instance, or raises
    ``Exception`` if the object is not found.
    """
    # Import here to avoid circular dependency at module level
    import gitlib

    pack_dir = os.path.join(repo.gitdir, "objects", "pack")
    if not os.path.isdir(pack_dir):
        raise Exception(f"Object {sha} not found (no pack directory)")

    for fname in os.listdir(pack_dir):
        if not fname.endswith('.idx'):
            continue

        idx_path = os.path.join(pack_dir, fname)
        pack_path = idx_path[:-4] + '.pack'
        if not os.path.isfile(pack_path):
            continue

        idx = PackIndex(idx_path)
        offset = idx.find_object(sha)
        if offset is None:
            continue

        pack = PackFile(pack_path, idx)
        obj_type, data = pack.read_object_at(offset)

        match obj_type:
            case b'commit': return gitlib.GitCommit(data)
            case b'tree':   return gitlib.GitTree(data)
            case b'tag':    return gitlib.GitTag(data)
            case b'blob':   return gitlib.GitBlob(data)
            case _:
                raise Exception(f"Unknown resolved type: {obj_type}")

    raise Exception(f"Object {sha} not found in any packfile")
