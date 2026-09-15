#!/usr/bin/env python3
"""dm-verity volume forensic analysis tool.

Parses on-disk superblocks, independently verifies Merkle hash tree integrity,
detects data block corruption, and generates device-mapper target table strings.
"""

import argparse
import hashlib
import json
import struct
import sys
import uuid as _uuid

VERITY_MAGIC = b"verity\x00\x00"
SB_SIZE = 512


def parse_superblock(path, offset=0):
    """Parse the dm-verity on-disk superblock (512-byte struct).

    Layout (all integers little-endian):
        0..7:    signature  "verity\\0\\0"
        8..11:   version    uint32
       12..15:   hash_type  uint32
       16..31:   uuid       16 bytes (RFC 4122)
       32..63:   algorithm  32-byte null-terminated ASCII
       64..67:   data_block_size  uint32
       68..71:   hash_block_size  uint32
       72..79:   data_blocks      uint64
       80..81:   salt_size        uint16
       82..87:   padding
       88..343:  salt       256 bytes (salt_size meaningful)
      344..511:  padding
    """
    with open(path, "rb") as f:
        f.seek(offset)
        raw = f.read(SB_SIZE)

    if len(raw) < SB_SIZE or raw[:8] != VERITY_MAGIC:
        return None

    version = struct.unpack_from("<I", raw, 8)[0]
    hash_type = struct.unpack_from("<I", raw, 12)[0]
    sb_uuid = str(_uuid.UUID(bytes=raw[16:32]))
    algorithm = raw[32:64].split(b"\x00", 1)[0].decode("ascii")
    dbs = struct.unpack_from("<I", raw, 64)[0]
    hbs = struct.unpack_from("<I", raw, 68)[0]
    data_blocks = struct.unpack_from("<Q", raw, 72)[0]
    salt_size = struct.unpack_from("<H", raw, 80)[0]
    salt = raw[88 : 88 + salt_size].hex()

    return {
        "version": version,
        "hash_type": hash_type,
        "uuid": sb_uuid,
        "algorithm": algorithm,
        "data_block_size": dbs,
        "hash_block_size": hbs,
        "data_blocks": data_blocks,
        "salt_size": salt_size,
        "salt": salt,
    }


def _hash(alg, salt_bytes, data):
    """Compute dm-verity hash: H(salt || data)."""
    h = hashlib.new(alg)
    h.update(salt_bytes)
    h.update(data)
    return h.digest()


def build_merkle_tree(data_path, alg, dbs, hbs, nblocks, salt_hex):
    """Compute the full dm-verity Merkle hash tree.

    Returns (root_hash_hex, tree_bytes, levels_list).
    tree_bytes is the binary tree stored top-level first, leaf-level last
    (matching veritysetup's on-disk layout).
    levels_list[0] = leaf level bytes, levels_list[-1] = root-side level bytes.
    """
    salt = bytes.fromhex(salt_hex)
    dig_size = hashlib.new(alg).digest_size
    hashes_per_block = hbs // dig_size

    # Compute leaf hashes: H(salt || data_block)
    leaf_hashes = []
    with open(data_path, "rb") as f:
        for _ in range(nblocks):
            blk = f.read(dbs)
            if len(blk) < dbs:
                blk += b"\x00" * (dbs - len(blk))
            leaf_hashes.append(_hash(alg, salt, blk))

    # Build levels bottom-up
    levels = []  # levels[0] = leaf level, levels[-1] = root-side level
    current = leaf_hashes
    while len(current) > 1:
        level_data = bytearray()
        next_level = []
        for i in range(0, len(current), hashes_per_block):
            hash_block = bytearray(hbs)  # zero-padded
            for j in range(min(hashes_per_block, len(current) - i)):
                off = j * dig_size
                hash_block[off : off + dig_size] = current[i + j]
            level_data.extend(hash_block)
            next_level.append(_hash(alg, salt, bytes(hash_block)))
        levels.append(bytes(level_data))
        current = next_level

    root_hash = current[0].hex() if current else ""
    # On-disk layout: top level first (root side), leaf level last
    tree_bytes = b"".join(reversed(levels))
    return root_hash, tree_bytes, levels


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_parse(args):
    sb = parse_superblock(args.hash, args.hash_offset)
    if sb is None:
        sys.stderr.write("INVALID_SUPERBLOCK\n")
        sys.exit(1)
    json.dump(sb, sys.stdout, indent=2)
    sys.stdout.write("\n")


def cmd_audit(args):
    sb = parse_superblock(args.hash, args.hash_offset)
    if sb is None:
        sys.stderr.write("INVALID_SUPERBLOCK\n")
        sys.exit(1)

    alg = sb["algorithm"]
    dbs = sb["data_block_size"]
    hbs = sb["hash_block_size"]
    nblocks = sb["data_blocks"]
    salt_hex = sb["salt"]

    root_hash, comp_tree, levels = build_merkle_tree(
        args.data, alg, dbs, hbs, nblocks, salt_hex
    )

    # Hash tree on disk starts one hash_block_size after the superblock
    tree_offset = args.hash_offset + hbs
    with open(args.hash, "rb") as f:
        f.seek(tree_offset)
        stored_tree = f.read(len(comp_tree))

    tree_valid = stored_tree == comp_tree
    corrupted = []

    if not tree_valid and levels:
        dig_size = hashlib.new(alg).digest_size
        hpb = hbs // dig_size
        # Leaf level is levels[0]; in on-disk tree it comes last
        non_leaf_size = sum(len(lvl) for lvl in levels[1:])

        for i in range(nblocks):
            block_idx, hash_idx = divmod(i, hpb)
            offset = non_leaf_size + block_idx * hbs + hash_idx * dig_size
            if comp_tree[offset : offset + dig_size] != stored_tree[offset : offset + dig_size]:
                corrupted.append(i)

    report = {
        "root_hash": root_hash,
        "algorithm": alg,
        "data_blocks": nblocks,
        "tree_valid": tree_valid,
        "corrupted_blocks": sorted(corrupted),
        "corruption_pct": round(len(corrupted) / nblocks * 100, 4) if nblocks else 0.0,
    }
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")


def cmd_dm_table(args):
    sb = parse_superblock(args.hash, args.hash_offset)
    if sb is None:
        sys.stderr.write("INVALID_SUPERBLOCK\n")
        sys.exit(1)

    root_hash, _, _ = build_merkle_tree(
        args.data,
        sb["algorithm"],
        sb["data_block_size"],
        sb["hash_block_size"],
        sb["data_blocks"],
        sb["salt"],
    )

    num_sectors = sb["data_blocks"] * sb["data_block_size"] // 512
    # hash_start_block: block index where the hash tree begins on the hash device
    # Superblock occupies one hash block, so tree starts at hash_offset/hbs + 1
    hash_start = (args.hash_offset + sb["hash_block_size"]) // sb["hash_block_size"]

    print(
        f"0 {num_sectors} verity {sb['version']} "
        f"{args.data_dev} {args.hash_dev} "
        f"{sb['data_block_size']} {sb['hash_block_size']} "
        f"{sb['data_blocks']} {hash_start} "
        f"{sb['algorithm']} {root_hash} {sb['salt']}"
    )


def main():
    parser = argparse.ArgumentParser(description="dm-verity forensic analysis tool")
    sub = parser.add_subparsers(dest="command")

    p_parse = sub.add_parser("parse", help="Parse verity superblock")
    p_parse.add_argument("--hash", required=True, help="Hash device/image path")
    p_parse.add_argument("--hash-offset", type=int, default=0, help="Byte offset to hash area")

    p_audit = sub.add_parser("audit", help="Audit volume integrity")
    p_audit.add_argument("--data", required=True, help="Data device/image path")
    p_audit.add_argument("--hash", required=True, help="Hash device/image path")
    p_audit.add_argument("--hash-offset", type=int, default=0, help="Byte offset to hash area")

    p_table = sub.add_parser("dm-table", help="Generate DM target table")
    p_table.add_argument("--data", required=True, help="Data device/image path")
    p_table.add_argument("--hash", required=True, help="Hash device/image path")
    p_table.add_argument("--hash-offset", type=int, default=0, help="Byte offset to hash area")
    p_table.add_argument("--data-dev", required=True, help="Data device path for table")
    p_table.add_argument("--hash-dev", required=True, help="Hash device path for table")

    args = parser.parse_args()
    handlers = {"parse": cmd_parse, "audit": cmd_audit, "dm-table": cmd_dm_table}
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)
    handler(args)


if __name__ == "__main__":
    main()
