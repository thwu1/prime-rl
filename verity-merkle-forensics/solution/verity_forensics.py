#!/usr/bin/env python3
"""
dm-verity forensic analysis tool.

Parses the on-disk dm-verity superblock, reconstructs the hash tree layout,
computes root hashes, and identifies corrupted data blocks by comparing
computed block hashes against stored leaf-level hashes.

Handles varying hash algorithms and hash block sizes across images.
"""

import hashlib
import json
import math
import os
import struct
import sys

IMAGE_DIR = "/app/images"
MANIFEST_PATH = "/app/manifest.json"
REPORT_PATH = "/app/report.json"

VERITY_SIGNATURE = b"verity\x00\x00"


def parse_superblock(raw):
    """
    Parse the dm-verity on-disk superblock (first 512 bytes of hash area).

    Layout (little-endian):
      0-7:    signature  "verity\\0\\0"
      8-11:   version    uint32
      12-15:  hash_type  uint32
      16-31:  uuid       16 bytes
      32-63:  algorithm  null-terminated ASCII (32 bytes)
      64-67:  data_block_size  uint32
      68-71:  hash_block_size  uint32
      72-79:  data_blocks      uint64
      80-81:  salt_size         uint16
      82-87:  padding
      88-343: salt             256 bytes (only salt_size used)
      344-511: padding
    """
    if len(raw) < 512:
        raise ValueError("Superblock data too short")

    sig = raw[0:8]
    if sig != VERITY_SIGNATURE:
        raise ValueError(f"Bad verity signature: {sig!r}")

    version = struct.unpack_from("<I", raw, 8)[0]
    algorithm = raw[32:64].split(b"\x00", 1)[0].decode("ascii")
    data_block_size = struct.unpack_from("<I", raw, 64)[0]
    hash_block_size = struct.unpack_from("<I", raw, 68)[0]
    data_blocks = struct.unpack_from("<Q", raw, 72)[0]
    salt_size = struct.unpack_from("<H", raw, 80)[0]
    salt = raw[88 : 88 + salt_size]

    return {
        "version": version,
        "algorithm": algorithm,
        "data_block_size": data_block_size,
        "hash_block_size": hash_block_size,
        "data_blocks": data_blocks,
        "salt": salt,
    }


def verity_hash(algorithm, salt, block_data, version=1):
    """Compute a single dm-verity hash: H(salt || block) for version >= 1."""
    h = hashlib.new(algorithm)
    if version >= 1:
        h.update(salt)
        h.update(block_data)
    else:
        h.update(block_data)
        h.update(salt)
    return h.digest()


def compute_level_block_counts(data_blocks, fan_out):
    """
    Return a list of hash-block counts per tree level.
    Index 0 = leaf level (hashes of data blocks), last index = top level.
    The top level always has exactly 1 block.
    """
    counts = []
    n = data_blocks
    while n > 1:
        n = math.ceil(n / fan_out)
        counts.append(n)
    if not counts:
        counts.append(1)
    return counts


def analyze_image(image_path, hash_offset):
    """Analyze one dm-verity protected image."""
    with open(image_path, "rb") as f:
        # ── Parse superblock ────────────────────────────────────
        f.seek(hash_offset)
        sb_raw = f.read(4096)  # read enough for any block size
        sb = parse_superblock(sb_raw)

        alg = sb["algorithm"]
        dbs = sb["data_block_size"]
        hbs = sb["hash_block_size"]
        n_data = sb["data_blocks"]
        salt = sb["salt"]
        ver = sb["version"]

        digest_size = hashlib.new(alg).digest_size
        fan_out = hbs // digest_size  # hashes per hash block

        # ── Compute tree level sizes ────────────────────────────
        level_blocks = compute_level_block_counts(n_data, fan_out)
        n_levels = len(level_blocks)

        # ── Compute on-disk byte offsets for each level ─────────
        # Layout after superblock (which occupies 1 hbs-sized block):
        #   top level first, then lower levels, leaf level last.
        level_offsets = [0] * n_levels
        pos = hash_offset + hbs  # first byte after superblock
        for i in range(n_levels - 1, -1, -1):
            level_offsets[i] = pos
            pos += level_blocks[i] * hbs

        # ── Compute root hash from stored top-level block ───────
        f.seek(level_offsets[n_levels - 1])
        top_block = f.read(hbs)
        root_hash = verity_hash(alg, salt, top_block, ver).hex()

        # ── Read all leaf-level hash data ───────────────────────
        f.seek(level_offsets[0])
        leaf_data = f.read(level_blocks[0] * hbs)

        # ── Compare each data block hash against stored leaf ────
        corrupted = []
        for i in range(n_data):
            f.seek(i * dbs)
            data_block = f.read(dbs)
            computed = verity_hash(alg, salt, data_block, ver)

            blk_idx = i // fan_out
            hash_pos = i % fan_out
            offset_in_leaf = blk_idx * hbs + hash_pos * digest_size
            stored = leaf_data[offset_in_leaf : offset_in_leaf + digest_size]

            if computed != stored:
                corrupted.append(i)

    return {
        "root_hash": root_hash,
        "hash_algorithm": alg,
        "integrity": "clean" if not corrupted else "corrupted",
        "corrupted_data_blocks": corrupted,
    }


def main():
    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    report = {"images": {}}

    for name in sorted(manifest):
        info = manifest[name]
        path = os.path.join(IMAGE_DIR, name)
        if not os.path.isfile(path):
            print(f"  SKIP {name}: file not found", file=sys.stderr)
            continue

        result = analyze_image(path, info["hash_offset"])
        report["images"][name] = result

        n_bad = len(result["corrupted_data_blocks"])
        tag = result["integrity"]
        if n_bad:
            tag += f" ({n_bad} block{'s' if n_bad != 1 else ''})"
        print(
            f"  {name}: {tag}  alg={result['hash_algorithm']}  "
            f"root={result['root_hash'][:16]}..."
        )

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nReport written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
