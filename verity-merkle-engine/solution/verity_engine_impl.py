#!/usr/bin/env python3
"""dm-verity Merkle Hash Tree Engine — reference implementation.

Computes dm-verity v1 compatible hash trees matching veritysetup format
--no-superblock output exactly.
"""

import hashlib
import argparse
import math
import sys


def _hash(algo, salt, data):
    """dm-verity v1 block hash: H(salt || data)."""
    h = hashlib.new(algo)
    h.update(salt)
    h.update(data)
    return h.digest()


def _build_tree(data_bytes, algo, salt, dbs, hbs):
    """Build the Merkle hash tree bottom-up.

    Returns (root_hash_hex, levels) where levels[0] is the leaf level
    (closest to data) and levels[-1] is the top level.  Each level is
    a list of hash-block byte strings of length *hbs*.
    """
    digest_size = hashlib.new(algo).digest_size
    hpb = hbs // digest_size  # hashes that fit in one hash block
    nblocks = len(data_bytes) // dbs

    if nblocks == 0:
        print("Error: no complete data blocks in input", file=sys.stderr)
        sys.exit(1)

    # --- leaf hashes (one per data block) ---
    hashes = []
    for i in range(nblocks):
        blk = data_bytes[i * dbs : (i + 1) * dbs]
        hashes.append(_hash(algo, salt, blk))

    # --- build levels ---
    levels = []
    while len(hashes) > 1:
        nblk = math.ceil(len(hashes) / hpb)
        level_blocks = []
        next_hashes = []
        for i in range(nblk):
            start = i * hpb
            end = min(start + hpb, len(hashes))
            block_data = b"".join(hashes[start:end])
            pad = hbs - len(block_data)
            if pad > 0:
                block_data += b"\x00" * pad
            level_blocks.append(block_data)
            next_hashes.append(_hash(algo, salt, block_data))
        levels.append(level_blocks)
        hashes = next_hashes

    # Edge case: single data block still needs one tree level
    if not levels and nblocks == 1:
        block_data = hashes[0] + b"\x00" * (hbs - digest_size)
        levels.append([block_data])
        hashes = [_hash(algo, salt, block_data)]

    return hashes[0].hex(), levels


# ---- subcommands -----------------------------------------------------------

def cmd_format(args):
    salt = bytes.fromhex(args.salt)
    with open(args.data, "rb") as f:
        data = f.read()

    root_hash, levels = _build_tree(
        data, args.algorithm, salt, args.data_block_size, args.hash_block_size
    )

    # Write tree: top level first, then descending to leaf level
    with open(args.hash_output, "wb") as f:
        for level in reversed(levels):
            for blk in level:
                f.write(blk)

    print(root_hash)


def cmd_verify(args):
    salt = bytes.fromhex(args.salt)
    algo = args.algorithm
    dbs = args.data_block_size
    hbs = args.hash_block_size
    digest_size = hashlib.new(algo).digest_size
    hpb = hbs // digest_size

    with open(args.data, "rb") as f:
        data = f.read()
    nblocks = len(data) // dbs

    with open(args.hash_file, "rb") as f:
        tree_bytes = f.read()

    # Compute level block counts (level 0 = leaf, ascending)
    level_counts = []
    n = nblocks
    while n > 1:
        nblk = math.ceil(n / hpb)
        level_counts.append(nblk)
        n = nblk
    if not level_counts and nblocks == 1:
        level_counts.append(1)

    # On-disk order is top-first → leaf offset = sum of higher-level blocks
    leaf_offset = sum(level_counts[1:]) * hbs if len(level_counts) > 1 else 0

    # Compare each data block hash against stored leaf hash
    corrupted = []
    for i in range(nblocks):
        blk = data[i * dbs : (i + 1) * dbs]
        actual = _hash(algo, salt, blk)
        bidx = i // hpb
        hidx = i % hpb
        off = leaf_offset + bidx * hbs + hidx * digest_size
        expected = tree_bytes[off : off + digest_size]
        if actual != expected:
            corrupted.append(i)

    if corrupted:
        print("CORRUPTED")
        for b in corrupted:
            print(f"block {b}")
        sys.exit(1)

    # All leaf hashes match — verify root hash via full recomputation
    root_hash, _ = _build_tree(data, algo, salt, dbs, hbs)
    if root_hash != args.root_hash:
        print("ROOT_HASH_MISMATCH")
        sys.exit(1)

    print("OK")
    sys.exit(0)


# ---- CLI -------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="dm-verity Merkle Hash Tree Engine"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    fmt = sub.add_parser("format")
    fmt.add_argument("--data", required=True)
    fmt.add_argument("--hash-output", required=True)
    fmt.add_argument("--salt", required=True, help="Salt in hexadecimal")
    fmt.add_argument("--algorithm", default="sha256")
    fmt.add_argument("--data-block-size", type=int, default=4096)
    fmt.add_argument("--hash-block-size", type=int, default=4096)

    ver = sub.add_parser("verify")
    ver.add_argument("--data", required=True)
    ver.add_argument("--hash-file", required=True)
    ver.add_argument("--root-hash", required=True)
    ver.add_argument("--salt", required=True, help="Salt in hexadecimal")
    ver.add_argument("--algorithm", default="sha256")
    ver.add_argument("--data-block-size", type=int, default=4096)
    ver.add_argument("--hash-block-size", type=int, default=4096)

    args = parser.parse_args()
    if args.command == "format":
        cmd_format(args)
    elif args.command == "verify":
        cmd_verify(args)


if __name__ == "__main__":
    main()
