#!/usr/bin/env python3
"""Git packfile reader — parses .pack v2 and .idx v2 files, resolves deltas.

"""

import hashlib
import os
import struct
import sys
import zlib


# ---------------------------------------------------------------------------
# Pack Index v2
# ---------------------------------------------------------------------------

class PackIndex:
    """Parser for Git pack index v2 (.idx) files.

    Layout:
      - 4-byte magic  0xff744f63
      - 4-byte version (2)
      - 256 x 4-byte fanout table
      - N x 20-byte sorted SHA-1 table
      - N x 4-byte CRC32 table
      - N x 4-byte offset table (MSB set ⇒ large-offset index)
      - optional large-offset table (8-byte entries)
      - 20-byte pack checksum
      - 20-byte index checksum
    """

    def __init__(self, path):
        with open(path, "rb") as f:
            self.data = f.read()

        magic = self.data[:4]
        if magic != b"\xfftOc":
            raise ValueError(f"Invalid idx magic: {magic!r}")
        version = struct.unpack(">I", self.data[4:8])[0]
        if version != 2:
            raise ValueError(f"Unsupported idx version: {version}")

        # Fanout table (256 entries)
        self.fanout = struct.unpack(">256I", self.data[8 : 8 + 1024])
        self.num_objects = self.fanout[255]

        self._sha_off = 8 + 1024
        self._crc_off = self._sha_off + self.num_objects * 20
        self._ofs_off = self._crc_off + self.num_objects * 4
        self._large_off = self._ofs_off + self.num_objects * 4

        # Build SHA hex -> sequential index mapping
        self._sha_to_idx = {}
        for i in range(self.num_objects):
            start = self._sha_off + i * 20
            sha_hex = self.data[start : start + 20].hex()
            self._sha_to_idx[sha_hex] = i

    def get_offset(self, sha_hex):
        """Return pack-file byte offset for *sha_hex*, or None."""
        idx = self._sha_to_idx.get(sha_hex)
        if idx is None:
            return None
        raw = struct.unpack(">I", self.data[self._ofs_off + idx * 4 : self._ofs_off + idx * 4 + 4])[0]
        if raw & 0x80000000:
            large_idx = raw & 0x7FFFFFFF
            pos = self._large_off + large_idx * 8
            return struct.unpack(">Q", self.data[pos : pos + 8])[0]
        return raw

    def list_objects(self):
        """Return a sorted list of all SHA-1 hex strings."""
        shas = []
        for i in range(self.num_objects):
            start = self._sha_off + i * 20
            shas.append(self.data[start : start + 20].hex())
        return shas  # already sorted (idx spec)


# ---------------------------------------------------------------------------
# Pack File v2
# ---------------------------------------------------------------------------

OBJ_COMMIT = 1
OBJ_TREE = 2
OBJ_BLOB = 3
OBJ_TAG = 4
OBJ_OFS_DELTA = 6
OBJ_REF_DELTA = 7

TYPE_NAMES = {OBJ_COMMIT: "commit", OBJ_TREE: "tree", OBJ_BLOB: "blob", OBJ_TAG: "tag"}


class _RefDelta(Exception):
    """Sentinel: REF_DELTA needs cross-pack resolution."""

    def __init__(self, base_sha, delta_data):
        self.base_sha = base_sha
        self.delta_data = delta_data


class PackFile:
    """Parser for Git pack v2 (.pack) files."""

    def __init__(self, path):
        with open(path, "rb") as f:
            self.data = f.read()
        magic = self.data[:4]
        if magic != b"PACK":
            raise ValueError(f"Invalid pack magic: {magic!r}")
        self.version = struct.unpack(">I", self.data[4:8])[0]
        if self.version not in (2, 3):
            raise ValueError(f"Unsupported pack version: {self.version}")
        self.num_objects = struct.unpack(">I", self.data[8:12])[0]

    # -- low-level readers --------------------------------------------------

    def _read_type_and_size(self, offset):
        """Variable-length type+size.  Returns (type, size, next_offset)."""
        b = self.data[offset]
        obj_type = (b >> 4) & 0x7
        size = b & 0x0F
        shift = 4
        offset += 1
        while b & 0x80:
            b = self.data[offset]
            size |= (b & 0x7F) << shift
            shift += 7
            offset += 1
        return obj_type, size, offset

    def _read_ofs_delta_offset(self, offset):
        """OFS_DELTA negative-offset encoding.  Returns (neg_offset, next_offset)."""
        b = self.data[offset]
        result = b & 0x7F
        offset += 1
        while b & 0x80:
            b = self.data[offset]
            result = ((result + 1) << 7) | (b & 0x7F)
            offset += 1
        return result, offset

    def _zlib_decompress(self, offset):
        """Decompress zlib stream starting at *offset*.  Returns (data, consumed)."""
        dec = zlib.decompressobj()
        out = dec.decompress(self.data[offset:])
        consumed = len(self.data) - offset - len(dec.unused_data)
        return out, consumed

    # -- delta application --------------------------------------------------

    @staticmethod
    def _apply_delta(base, delta):
        """Apply a git delta buffer to *base*, return the target bytes."""
        idx = 0

        def _read_varint():
            nonlocal idx
            val = 0
            shift = 0
            while True:
                b = delta[idx]
                idx += 1
                val |= (b & 0x7F) << shift
                shift += 7
                if not (b & 0x80):
                    return val

        _src_size = _read_varint()
        tgt_size = _read_varint()

        out = bytearray()
        while idx < len(delta):
            cmd = delta[idx]
            idx += 1

            if cmd & 0x80:  # ---- COPY from base ----
                cp_off = 0
                cp_sz = 0
                if cmd & 0x01:
                    cp_off = delta[idx]; idx += 1
                if cmd & 0x02:
                    cp_off |= delta[idx] << 8; idx += 1
                if cmd & 0x04:
                    cp_off |= delta[idx] << 16; idx += 1
                if cmd & 0x08:
                    cp_off |= delta[idx] << 24; idx += 1
                if cmd & 0x10:
                    cp_sz = delta[idx]; idx += 1
                if cmd & 0x20:
                    cp_sz |= delta[idx] << 8; idx += 1
                if cmd & 0x40:
                    cp_sz |= delta[idx] << 16; idx += 1
                if cp_sz == 0:
                    cp_sz = 0x10000
                out.extend(base[cp_off : cp_off + cp_sz])

            elif cmd:  # ---- INSERT literal ----
                out.extend(delta[idx : idx + cmd])
                idx += cmd

            else:
                raise ValueError("Reserved delta opcode 0")

        if len(out) != tgt_size:
            raise ValueError(f"Delta target size mismatch: got {len(out)}, want {tgt_size}")
        return bytes(out)

    # -- object reading -----------------------------------------------------

    def read_object_at(self, offset):
        """Read and fully resolve the object at *offset*.

        Returns (type_int, data).  Raises _RefDelta if resolution requires
        a cross-pack SHA lookup (handled by PackReader).
        """
        obj_type, _size, data_off = self._read_type_and_size(offset)

        if obj_type == OBJ_OFS_DELTA:
            neg, data_off = self._read_ofs_delta_offset(data_off)
            delta_data, _ = self._zlib_decompress(data_off)
            base_type, base_data = self.read_object_at(offset - neg)
            return base_type, self._apply_delta(base_data, delta_data)

        if obj_type == OBJ_REF_DELTA:
            base_sha = self.data[data_off : data_off + 20].hex()
            delta_data, _ = self._zlib_decompress(data_off + 20)
            raise _RefDelta(base_sha, delta_data)

        data, _ = self._zlib_decompress(data_off)
        return obj_type, data


# ---------------------------------------------------------------------------
# High-level reader (multiple packs)
# ---------------------------------------------------------------------------

class PackReader:
    """Combines one or more .idx/.pack pairs into a single object store."""

    def __init__(self, pack_dir):
        self._indices = []
        self._packs = {}  # id(index) -> PackFile

        idx_names = sorted(f for f in os.listdir(pack_dir) if f.endswith(".idx"))
        for idx_name in idx_names:
            pack_name = idx_name[:-4] + ".pack"
            pack_path = os.path.join(pack_dir, pack_name)
            if not os.path.exists(pack_path):
                continue
            idx = PackIndex(os.path.join(pack_dir, idx_name))
            pf = PackFile(pack_path)
            self._indices.append(idx)
            self._packs[id(idx)] = pf

    def list_objects(self):
        seen = set()
        for idx in self._indices:
            for s in idx.list_objects():
                seen.add(s)
        return sorted(seen)

    def read_object(self, sha_hex):
        """Return (type_name, raw_data)."""
        for idx in self._indices:
            offset = idx.get_offset(sha_hex)
            if offset is None:
                continue
            pf = self._packs[id(idx)]
            try:
                t, d = pf.read_object_at(offset)
            except _RefDelta as rd:
                base_name, base_data = self.read_object(rd.base_sha)
                d = PackFile._apply_delta(base_data, rd.delta_data)
                return base_name, d
            return TYPE_NAMES[t], d
        raise KeyError(f"Object {sha_hex} not found")

    # convenience wrappers
    def cat(self, sha):
        return self.read_object(sha)[1]

    def type_of(self, sha):
        return self.read_object(sha)[0]

    def size_of(self, sha):
        return len(self.read_object(sha)[1])

    def ls_tree(self, sha):
        tname, data = self.read_object(sha)
        if tname != "tree":
            raise ValueError(f"Not a tree object: {tname}")
        entries = []
        i = 0
        while i < len(data):
            sp = data.index(b" ", i)
            mode = data[i:sp].decode("ascii")
            nul = data.index(b"\x00", sp)
            name = data[sp + 1 : nul].decode("utf-8")
            entry_sha = data[nul + 1 : nul + 21].hex()
            mode6 = mode.zfill(6)
            if mode.startswith("4"):
                etype = "tree"
            elif mode == "160000":
                etype = "commit"
            else:
                etype = "blob"
            entries.append((mode6, etype, entry_sha, name))
            i = nul + 21
        return entries

    def log(self, sha):
        commits = []
        visited = set()
        queue = [sha]
        while queue:
            cur = queue.pop(0)
            if cur in visited:
                continue
            visited.add(cur)
            tname, data = self.read_object(cur)
            if tname != "commit":
                continue
            info = self._parse_commit(data)
            commits.append((cur, info))
            for p in info.get("parent", []):
                if p not in visited:
                    queue.append(p)
        return commits

    @staticmethod
    def _parse_commit(data):
        text = data.decode("utf-8", errors="replace")
        header, _, message = text.partition("\n\n")
        info = {"message": message, "parent": []}
        for line in header.split("\n"):
            if line.startswith(" "):
                continue
            if " " in line:
                key, val = line.split(" ", 1)
                if key == "parent":
                    info["parent"].append(val)
                else:
                    info[key] = val
        return info

    def verify(self):
        results = []
        for idx in self._indices:
            pf = self._packs[id(idx)]
            pack_body = pf.data[:-20]
            expected = pf.data[-20:].hex()
            actual = hashlib.sha1(pack_body).hexdigest()
            results.append(
                {"valid": actual == expected, "expected": expected, "actual": actual, "n": pf.num_objects}
            )
        return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 3:
        print(
            "Usage: packfile_reader.py <pack_dir> <command> [args]\n"
            "Commands: list  type <sha>  size <sha>  cat <sha>  ls-tree <sha>  log <sha>  verify",
            file=sys.stderr,
        )
        sys.exit(1)

    pack_dir = sys.argv[1]
    cmd = sys.argv[2]
    reader = PackReader(pack_dir)

    if cmd == "list":
        for s in reader.list_objects():
            print(s)

    elif cmd == "type":
        print(reader.type_of(sys.argv[3]))

    elif cmd == "size":
        print(reader.size_of(sys.argv[3]))

    elif cmd == "cat":
        sys.stdout.buffer.write(reader.cat(sys.argv[3]))

    elif cmd == "ls-tree":
        for mode, etype, esha, name in reader.ls_tree(sys.argv[3]):
            print(f"{mode} {etype} {esha}\t{name}")

    elif cmd == "log":
        for csha, info in reader.log(sys.argv[3]):
            print(f"commit {csha}")
            if "author" in info:
                print(f"Author: {info['author']}")
            print()
            msg = info["message"].strip()
            for line in msg.split("\n"):
                print(f"    {line}")
            print()

    elif cmd == "verify":
        results = reader.verify()
        ok = True
        for r in results:
            status = "OK" if r["valid"] else "FAILED"
            print(f"Pack: {r['n']} objects, checksum {status}")
            if not r["valid"]:
                ok = False
        sys.exit(0 if ok else 1)

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
