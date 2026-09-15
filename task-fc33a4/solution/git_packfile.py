#!/usr/bin/env python3
"""
Git v2 packfile parser — extracts all objects as loose git objects.

Usage: python3 git_packfile.py <packfile.pack> <output_dir>

Supports base objects (commit, tree, blob, tag) and deltified objects
(OFS_DELTA, REF_DELTA) including chained deltas.  Only uses stdlib.
"""

import sys
import os
import zlib
import hashlib
import struct

# ── Pack object type IDs ──────────────────────────────────────
OBJ_COMMIT = 1
OBJ_TREE = 2
OBJ_BLOB = 3
OBJ_TAG = 4
OBJ_OFS_DELTA = 6
OBJ_REF_DELTA = 7

TYPE_NAME = {
    OBJ_COMMIT: b"commit",
    OBJ_TREE: b"tree",
    OBJ_BLOB: b"blob",
    OBJ_TAG: b"tag",
}


# ── Low-level readers ────────────────────────────────────────

def _read_obj_header(data, off):
    """Variable-length object header → (type_id, uncompressed_size, new_off)."""
    b = data[off]
    typ = (b >> 4) & 0x07
    size = b & 0x0F
    shift = 4
    off += 1
    while b & 0x80:
        b = data[off]
        size |= (b & 0x7F) << shift
        shift += 7
        off += 1
    return typ, size, off


def _read_ofs_offset(data, off):
    """OFS_DELTA negative-offset encoding → (offset_value, new_off).

    Each continuation byte contributes ((accumulated+1)<<7) | low7.
    """
    b = data[off]
    val = b & 0x7F
    off += 1
    while b & 0x80:
        b = data[off]
        val = ((val + 1) << 7) | (b & 0x7F)
        off += 1
    return val, off


def _read_varint(data, off):
    """Standard little-endian varint (7 bits/byte, MSB continuation)."""
    result = 0
    shift = 0
    while True:
        b = data[off]
        result |= (b & 0x7F) << shift
        off += 1
        if not (b & 0x80):
            break
        shift += 7
    return result, off


def _zlib_stream(data, off):
    """Decompress one zlib stream → (decompressed, bytes_consumed)."""
    d = zlib.decompressobj()
    buf = data[off:]
    out = d.decompress(buf)
    out += d.flush()
    consumed = len(buf) - len(d.unused_data)
    return out, consumed


# ── Delta application ────────────────────────────────────────

def _apply_delta(base, delta):
    """Apply a git binary delta to *base*, returning the target bytes."""
    pos = 0
    src_len, pos = _read_varint(delta, pos)
    tgt_len, pos = _read_varint(delta, pos)
    if len(base) != src_len:
        raise ValueError(
            f"delta src_len {src_len} != actual base length {len(base)}"
        )

    out = bytearray()
    while pos < len(delta):
        cmd = delta[pos]; pos += 1
        if cmd & 0x80:                       # ── COPY from base ──
            cp_off = 0; cp_sz = 0
            if cmd & 0x01: cp_off  = delta[pos]; pos += 1
            if cmd & 0x02: cp_off |= delta[pos] << 8;  pos += 1
            if cmd & 0x04: cp_off |= delta[pos] << 16; pos += 1
            if cmd & 0x08: cp_off |= delta[pos] << 24; pos += 1
            if cmd & 0x10: cp_sz   = delta[pos]; pos += 1
            if cmd & 0x20: cp_sz  |= delta[pos] << 8;  pos += 1
            if cmd & 0x40: cp_sz  |= delta[pos] << 16; pos += 1
            if cp_sz == 0:
                cp_sz = 0x10000
            out.extend(base[cp_off : cp_off + cp_sz])
        elif cmd:                            # ── INSERT literal ──
            out.extend(delta[pos : pos + cmd])
            pos += cmd
        else:
            raise ValueError("invalid delta opcode 0x00")

    if len(out) != tgt_len:
        raise ValueError(
            f"delta target size mismatch: expected {tgt_len}, produced {len(out)}"
        )
    return bytes(out)


# ── Object identity helpers ──────────────────────────────────

def _object_sha(type_id, content):
    """Compute the SHA-1 hex digest for a git object."""
    hdr = TYPE_NAME[type_id] + b" " + str(len(content)).encode() + b"\x00"
    return hashlib.sha1(hdr + content).hexdigest()


def _write_loose(out_dir, sha, type_id, content):
    """Write a single loose git object to *out_dir*."""
    hdr = TYPE_NAME[type_id] + b" " + str(len(content)).encode() + b"\x00"
    compressed = zlib.compress(hdr + content)
    d = os.path.join(out_dir, sha[:2])
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, sha[2:]), "wb") as f:
        f.write(compressed)


# ── Main parser ──────────────────────────────────────────────

def parse_packfile(pack_path, out_dir):
    with open(pack_path, "rb") as f:
        data = f.read()

    # ── Checksum ──
    if hashlib.sha1(data[:-20]).digest() != data[-20:]:
        raise ValueError("packfile SHA-1 checksum mismatch")

    # ── Header ──
    if data[:4] != b"PACK":
        raise ValueError(f"bad magic {data[:4]!r}")
    version = struct.unpack(">I", data[4:8])[0]
    if version != 2:
        raise ValueError(f"unsupported pack version {version}")
    n_objects = struct.unpack(">I", data[8:12])[0]

    # ── First pass: read entries ──
    resolved = {}          # pack_offset → (type_id, content)
    by_sha   = {}          # sha_hex    → (type_id, content)
    pend_ofs = []          # (entry_off, base_abs_off, delta_bytes)
    pend_ref = []          # (entry_off, base_sha_hex, delta_bytes)

    off = 12
    for _ in range(n_objects):
        entry_off = off
        typ, _size, off = _read_obj_header(data, off)

        if typ in (OBJ_COMMIT, OBJ_TREE, OBJ_BLOB, OBJ_TAG):
            content, consumed = _zlib_stream(data, off)
            off += consumed
            sha = _object_sha(typ, content)
            resolved[entry_off] = (typ, content)
            by_sha[sha] = (typ, content)

        elif typ == OBJ_OFS_DELTA:
            neg, off = _read_ofs_offset(data, off)
            base_off = entry_off - neg
            delta, consumed = _zlib_stream(data, off)
            off += consumed
            pend_ofs.append((entry_off, base_off, delta))

        elif typ == OBJ_REF_DELTA:
            base_sha = data[off : off + 20].hex()
            off += 20
            delta, consumed = _zlib_stream(data, off)
            off += consumed
            pend_ref.append((entry_off, base_sha, delta))

        else:
            raise ValueError(f"unknown pack type {typ} at offset {entry_off}")

    # ── Resolve deltas (iterative for chains) ──
    for _ in range(len(pend_ofs) + len(pend_ref) + 1):
        if not pend_ofs and not pend_ref:
            break

        new_ofs = []
        for entry_off, base_off, delta in pend_ofs:
            if base_off in resolved:
                btyp, bdata = resolved[base_off]
                content = _apply_delta(bdata, delta)
                sha = _object_sha(btyp, content)
                resolved[entry_off] = (btyp, content)
                by_sha[sha] = (btyp, content)
            else:
                new_ofs.append((entry_off, base_off, delta))
        pend_ofs = new_ofs

        new_ref = []
        for entry_off, base_sha, delta in pend_ref:
            if base_sha in by_sha:
                btyp, bdata = by_sha[base_sha]
                content = _apply_delta(bdata, delta)
                sha = _object_sha(btyp, content)
                resolved[entry_off] = (btyp, content)
                by_sha[sha] = (btyp, content)
            else:
                new_ref.append((entry_off, base_sha, delta))
        pend_ref = new_ref
    else:
        if pend_ofs or pend_ref:
            raise ValueError(
                f"unresolved deltas: {len(pend_ofs)} OFS + {len(pend_ref)} REF"
            )

    # ── Write loose objects ──
    os.makedirs(out_dir, exist_ok=True)
    for sha, (tid, content) in by_sha.items():
        _write_loose(out_dir, sha, tid, content)

    return len(by_sha)


# ── CLI ──────────────────────────────────────────────────────

def main():
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <pack-file> <output-dir>", file=sys.stderr)
        sys.exit(1)
    pack_path, out_dir = sys.argv[1], sys.argv[2]
    if not os.path.isfile(pack_path):
        print(f"error: {pack_path}: not found", file=sys.stderr)
        sys.exit(1)
    n = parse_packfile(pack_path, out_dir)
    print(f"extracted {n} objects to {out_dir}")


if __name__ == "__main__":
    main()
