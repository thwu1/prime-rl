#!/usr/bin/env python3
"""
Construct an ext2 filesystem image from raw bytes.
Builds a 4 MiB ext2 image with the following structure:
  /lost+found/           (empty directory, mode 0700)
  /README                (text file)
  /data/                 (directory)
  /data/measurements.csv (CSV with computed values)
  /data/large.bin        (14 KiB, requires indirect block pointers)
"""

import struct

# ── Filesystem geometry ───────────────────────────────────────────────
IMAGE_SIZE       = 4 * 1024 * 1024          # 4 MiB
BLOCK_SIZE       = 1024
TOTAL_BLOCKS     = IMAGE_SIZE // BLOCK_SIZE  # 4096
INODES_PER_GROUP = 128
INODE_SIZE       = 128
BLOCKS_PER_GROUP = 8192                      # single block group
S_FIRST_DATA_BLOCK = 1                       # required for 1024-byte blocks

# ── Inode assignments ─────────────────────────────────────────────────
INO_ROOT       = 2
INO_LOST_FOUND = 11   # first non-reserved inode
INO_README     = 12
INO_DATA_DIR   = 13
INO_MEAS_CSV   = 14
INO_LARGE_BIN  = 15

# ── Block layout ─────────────────────────────────────────────────────
BLK_BOOT        = 0
BLK_SUPER       = 1
BLK_BGDT        = 2
BLK_BLOCK_BMP   = 3
BLK_INODE_BMP   = 4
BLK_INODE_TBL   = 5    # 16 blocks (5-20)
INODE_TBL_BLOCKS = (INODES_PER_GROUP * INODE_SIZE + BLOCK_SIZE - 1) // BLOCK_SIZE

BLK_ROOT_DIR    = 21
BLK_LOST_FOUND  = 22
BLK_README      = 23
BLK_DATA_DIR    = 24
BLK_MEAS_CSV    = 25
BLK_LARGE_START = 26   # 14 data blocks: 26-39
LARGE_BIN_NBLKS = 14
BLK_INDIRECT    = 40   # singly indirect block for large.bin

# ── Allocation tracking ──────────────────────────────────────────────
# Highest allocated block — used for bitmap and free-count bookkeeping.
LAST_USED_BLOCK = BLK_LARGE_START + LARGE_BIN_NBLKS - 1   # last data block of large.bin

# The block bitmap tracks blocks starting from S_FIRST_DATA_BLOCK;
# block 0 (boot sector) is outside the group and not tracked.
ALLOCATED_BLOCK_COUNT = LAST_USED_BLOCK - S_FIRST_DATA_BLOCK + 1
TRACKABLE_BLOCK_COUNT = TOTAL_BLOCKS - S_FIRST_DATA_BLOCK   # 4095
FREE_BLOCK_COUNT = TRACKABLE_BLOCK_COUNT - ALLOCATED_BLOCK_COUNT

USED_INODE_COUNT = 15   # inodes 1-15
FREE_INODE_COUNT = INODES_PER_GROUP - USED_INODE_COUNT

# ── Directory-entry file-type constants ───────────────────────────────
FT_REG = 1
FT_DIR = 2

# ── File contents ─────────────────────────────────────────────────────
README_BYTES = b"ext2 filesystem created from scratch for this task.\n"

_csv_rows = ["id,value,square"] + [f"{i},{i},{i*i}" for i in range(1, 11)]
MEAS_CSV_BYTES = ("\n".join(_csv_rows) + "\n").encode()

LARGE_BIN_SIZE = LARGE_BIN_NBLKS * BLOCK_SIZE   # 14336
LARGE_BIN_DATA = bytes(i % 251 for i in range(LARGE_BIN_SIZE))


# ── Helpers ───────────────────────────────────────────────────────────

def write_inode(img, ino, mode, size, links, i_blocks, direct_blks, indirect=0):
    """Write an inode at the correct offset in the inode table."""
    off = BLK_INODE_TBL * BLOCK_SIZE + (ino - 1) * INODE_SIZE
    struct.pack_into("<H", img, off + 0,  mode)
    struct.pack_into("<H", img, off + 2,  0)            # uid
    struct.pack_into("<I", img, off + 4,  size)
    struct.pack_into("<H", img, off + 24, 0)            # gid
    struct.pack_into("<H", img, off + 26, links)
    struct.pack_into("<I", img, off + 28, i_blocks)     # 512-byte sectors
    for i, blk in enumerate(direct_blks[:12]):
        struct.pack_into("<I", img, off + 40 + i * 4, blk)
    struct.pack_into("<I", img, off + 88, indirect)     # singly indirect


def write_dir_entry(img, base, pos, inode, name, ftype, is_last, blk_end):
    """Write a single directory entry.  If *is_last*, pad rec_len to block end."""
    name_b = name.encode() if isinstance(name, str) else name
    nlen = len(name_b)
    rec = (8 + nlen + 3) & ~3      # 4-byte aligned minimum
    if is_last:
        rec = blk_end - pos
    struct.pack_into("<I", img, base + pos, inode)
    struct.pack_into("<H", img, base + pos + 4, rec)
    img[base + pos + 6] = nlen
    img[base + pos + 7] = ftype
    img[base + pos + 8: base + pos + 8 + nlen] = name_b
    return pos + rec


# ── Main build routine ────────────────────────────────────────────────

def build():
    img = bytearray(IMAGE_SIZE)

    # ──────────── Superblock (block 1) ────────────
    sb = BLK_SUPER * BLOCK_SIZE
    struct.pack_into("<I", img, sb + 0,   INODES_PER_GROUP)     # s_inodes_count
    struct.pack_into("<I", img, sb + 4,   TOTAL_BLOCKS)         # s_blocks_count
    struct.pack_into("<I", img, sb + 8,   0)                    # s_r_blocks_count
    struct.pack_into("<I", img, sb + 12,  FREE_BLOCK_COUNT)     # s_free_blocks_count
    struct.pack_into("<I", img, sb + 16,  FREE_INODE_COUNT)     # s_free_inodes_count
    struct.pack_into("<I", img, sb + 20,  S_FIRST_DATA_BLOCK)   # s_first_data_block
    struct.pack_into("<I", img, sb + 24,  0)                    # s_log_block_size (1024)
    struct.pack_into("<I", img, sb + 28,  0)                    # s_log_frag_size
    struct.pack_into("<I", img, sb + 32,  BLOCKS_PER_GROUP)     # s_blocks_per_group
    struct.pack_into("<I", img, sb + 36,  BLOCKS_PER_GROUP)     # s_frags_per_group
    struct.pack_into("<I", img, sb + 40,  INODES_PER_GROUP)     # s_inodes_per_group
    struct.pack_into("<H", img, sb + 54,  0xFFFF)               # s_max_mnt_count
    struct.pack_into("<H", img, sb + 56,  0xEF53)               # s_magic
    struct.pack_into("<H", img, sb + 58,  1)                    # s_state (clean)
    struct.pack_into("<H", img, sb + 60,  1)                    # s_errors (continue)
    struct.pack_into("<I", img, sb + 76,  1)                    # s_rev_level (dynamic)
    struct.pack_into("<I", img, sb + 84,  11)                   # s_first_ino
    struct.pack_into("<H", img, sb + 88,  INODE_SIZE)           # s_inode_size
    struct.pack_into("<I", img, sb + 96,  0x0002)               # s_feature_incompat (FILETYPE)

    # ──────────── Block Group Descriptor (block 2) ────────────
    bg = BLK_BGDT * BLOCK_SIZE
    struct.pack_into("<I", img, bg + 0,   BLK_BLOCK_BMP)       # bg_block_bitmap
    struct.pack_into("<I", img, bg + 4,   BLK_INODE_BMP)       # bg_inode_bitmap
    struct.pack_into("<I", img, bg + 8,   BLK_INODE_TBL)       # bg_inode_table
    struct.pack_into("<H", img, bg + 12,  FREE_BLOCK_COUNT)     # bg_free_blocks_count
    struct.pack_into("<H", img, bg + 14,  FREE_INODE_COUNT)     # bg_free_inodes_count
    struct.pack_into("<H", img, bg + 16,  3)                    # bg_used_dirs_count

    # ──────────── Block Bitmap (block 3) ────────────
    bb = BLK_BLOCK_BMP * BLOCK_SIZE
    # Bit N in the bitmap represents block (S_FIRST_DATA_BLOCK + N).
    # Block 0 (boot sector) is not tracked by the bitmap.
    for blk in range(S_FIRST_DATA_BLOCK, LAST_USED_BLOCK + 1):
        bit = blk - S_FIRST_DATA_BLOCK
        img[bb + bit // 8] |= 1 << (bit % 8)
    # Padding: all bits for blocks beyond TOTAL_BLOCKS and excess bitmap bits
    for bit in range(TRACKABLE_BLOCK_COUNT, BLOCK_SIZE * 8):
        img[bb + bit // 8] |= 1 << (bit % 8)

    # ──────────── Inode Bitmap (block 4) ────────────
    ib = BLK_INODE_BMP * BLOCK_SIZE
    for idx in range(USED_INODE_COUNT):
        img[ib + idx // 8] |= 1 << (idx % 8)
    # Padding for non-existent inodes
    for bit in range(INODES_PER_GROUP, BLOCK_SIZE * 8):
        img[ib + bit // 8] |= 1 << (bit % 8)

    # ──────────── Inodes ────────────
    # Inodes 1, 3-10 are reserved; left zeroed (marked used in bitmap only).

    # Inode 2: root directory
    # links = 2 (for "." and "..") + number of subdirectories (lost+found)
    write_inode(img, INO_ROOT, mode=0o40755, size=BLOCK_SIZE,
                links=3, i_blocks=2, direct_blks=[BLK_ROOT_DIR])

    # Inode 11: /lost+found
    write_inode(img, INO_LOST_FOUND, mode=0o40700, size=BLOCK_SIZE,
                links=2, i_blocks=2, direct_blks=[BLK_LOST_FOUND])

    # Inode 12: /README
    write_inode(img, INO_README, mode=0o100644, size=len(README_BYTES),
                links=1, i_blocks=2, direct_blks=[BLK_README])

    # Inode 13: /data
    write_inode(img, INO_DATA_DIR, mode=0o40755, size=BLOCK_SIZE,
                links=2, i_blocks=2, direct_blks=[BLK_DATA_DIR])

    # Inode 14: /data/measurements.csv
    write_inode(img, INO_MEAS_CSV, mode=0o100644, size=len(MEAS_CSV_BYTES),
                links=1, i_blocks=2, direct_blks=[BLK_MEAS_CSV])

    # Inode 15: /data/large.bin  (14 data blocks + singly indirect block)
    # 14 data blocks, each 1024 bytes = 2 sectors of 512 bytes
    direct = list(range(BLK_LARGE_START, BLK_LARGE_START + 12))
    write_inode(img, INO_LARGE_BIN, mode=0o100644, size=LARGE_BIN_SIZE,
                links=1,
                i_blocks=LARGE_BIN_NBLKS * (BLOCK_SIZE // 512),
                direct_blks=direct, indirect=BLK_INDIRECT)

    # ──────────── Directory blocks ────────────
    # Root directory (block 21)
    base = BLK_ROOT_DIR * BLOCK_SIZE
    p = 0
    p = write_dir_entry(img, base, p, INO_ROOT,       ".",          FT_DIR, False, BLOCK_SIZE)
    p = write_dir_entry(img, base, p, INO_ROOT,       "..",         FT_DIR, False, BLOCK_SIZE)
    p = write_dir_entry(img, base, p, INO_LOST_FOUND, "lost+found", FT_DIR, False, BLOCK_SIZE)
    p = write_dir_entry(img, base, p, INO_README,     "README",     FT_REG, False, BLOCK_SIZE)
    p = write_dir_entry(img, base, p, INO_DATA_DIR,   "data",       FT_DIR, True,  BLOCK_SIZE)

    # lost+found directory (block 22)
    base = BLK_LOST_FOUND * BLOCK_SIZE
    p = 0
    p = write_dir_entry(img, base, p, INO_LOST_FOUND, ".",  FT_DIR, False, BLOCK_SIZE)
    p = write_dir_entry(img, base, p, INO_ROOT,       "..", FT_DIR, True,  BLOCK_SIZE)

    # data directory (block 24)
    base = BLK_DATA_DIR * BLOCK_SIZE
    p = 0
    p = write_dir_entry(img, base, p, INO_DATA_DIR,   ".",                FT_DIR, False, BLOCK_SIZE)
    p = write_dir_entry(img, base, p, INO_ROOT,       "..",               FT_DIR, False, BLOCK_SIZE)
    p = write_dir_entry(img, base, p, INO_MEAS_CSV,   "measurements.csv", FT_REG, False, BLOCK_SIZE)
    p = write_dir_entry(img, base, p, INO_LARGE_BIN,  "large.bin",        FT_REG, True,  BLOCK_SIZE)

    # ──────────── File data ────────────
    # README
    off = BLK_README * BLOCK_SIZE
    img[off:off + len(README_BYTES)] = README_BYTES

    # measurements.csv
    off = BLK_MEAS_CSV * BLOCK_SIZE
    img[off:off + len(MEAS_CSV_BYTES)] = MEAS_CSV_BYTES

    # large.bin (14 data blocks)
    for i in range(LARGE_BIN_NBLKS):
        blk = BLK_LARGE_START + i
        s = i * BLOCK_SIZE
        img[blk * BLOCK_SIZE:(blk + 1) * BLOCK_SIZE] = LARGE_BIN_DATA[s:s + BLOCK_SIZE]

    # Singly indirect block (block 40): pointers for data blocks 12-13
    ind = BLK_INDIRECT * BLOCK_SIZE
    for i in range(LARGE_BIN_NBLKS - 12):
        struct.pack_into("<I", img, ind + i * 4, BLK_LARGE_START + 12 + i)

    # ──────────── Write image ────────────
    with open("/app/ext2.img", "wb") as f:
        f.write(img)
    print(f"Wrote {len(img)} bytes to /app/ext2.img")


if __name__ == "__main__":
    build()
