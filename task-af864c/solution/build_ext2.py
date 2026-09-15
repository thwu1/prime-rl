#!/usr/bin/env python3
"""
Build a valid ext2 filesystem image entirely from raw binary I/O.

Constructs every on-disk structure (superblock, block group descriptor table,
block bitmap, inode bitmap, inode table, directory blocks, file data blocks,
and a singly indirect block) to produce an image that passes fsck.ext2 -fn.

Features: 5 directories, hard link (settings.bak -> settings.conf),
singly indirect block for large.bin (14 KiB), correct bitmap padding.
"""


import struct

# ============================================================
# Image Geometry
# ============================================================
IMAGE_SIZE       = 4 * 1024 * 1024        # 4 MiB
BLOCK_SIZE       = 1024
TOTAL_BLOCKS     = IMAGE_SIZE // BLOCK_SIZE  # 4096
BLOCKS_PER_GROUP = BLOCK_SIZE * 8           # 8192 (single block group)
INODES_COUNT     = 128
INODE_SIZE       = 128

S_FIRST_DATA_BLOCK = 1   # required for 1024-byte block size
S_FIRST_INO        = 11

# Feature flags
FINCOMPAT_FILETYPE = 0x0002

# Directory entry file types
FT_REG = 1
FT_DIR = 2

# ============================================================
# Block Layout
# ============================================================
BLK_SUPER   = 1
BLK_BGDT    = 2
BLK_BBITMAP = 3
BLK_IBITMAP = 4
BLK_ITABLE  = 5
ITABLE_NBLK = (INODES_COUNT * INODE_SIZE) // BLOCK_SIZE  # 16

_b = BLK_ITABLE + ITABLE_NBLK  # first data block = 21

BLK_ROOT_DIR    = _b; _b += 1        # 21
BLK_LOST_FOUND  = _b; _b += 1        # 22
BLK_README      = _b; _b += 1        # 23
BLK_DATA_DIR    = _b; _b += 1        # 24
BLK_MEAS_CSV    = _b; _b += 1        # 25
BLK_LB_DIRECT   = list(range(_b, _b + 12)); _b += 12  # 26-37
BLK_LB_INDIRECT = _b; _b += 1        # 38
BLK_LB_EXTRA    = list(range(_b, _b + 2)); _b += 2    # 39-40
BLK_CONFIG_DIR  = _b; _b += 1        # 41
BLK_SETTINGS    = _b; _b += 1        # 42
BLK_LOGS_DIR    = _b; _b += 1        # 43
BLK_ACCESS_LOG  = _b; _b += 1        # 44

LAST_USED_BLOCK = _b - 1  # 44

# ============================================================
# Inode Assignments
# ============================================================
INO_ROOT       = 2
INO_LOST_FOUND = 11
INO_README     = 12
INO_DATA_DIR   = 13
INO_MEAS_CSV   = 14
INO_LARGE_BIN  = 15
INO_CONFIG_DIR = 16
INO_SETTINGS   = 17   # shared by settings.conf AND settings.bak (hard link)
INO_LOGS_DIR   = 18
INO_ACCESS_LOG = 19

USED_INODES = 19

# ============================================================
# Derived Counts
# ============================================================
ALLOC_BLOCKS = LAST_USED_BLOCK - S_FIRST_DATA_BLOCK + 1  # 44
TRACKABLE    = TOTAL_BLOCKS - S_FIRST_DATA_BLOCK          # 4095
FREE_BLOCKS  = TRACKABLE - ALLOC_BLOCKS                    # 4051
FREE_INODES  = INODES_COUNT - USED_INODES                  # 109
USED_DIRS    = 5  # root, lost+found, data, config, logs

# ============================================================
# File Contents
# ============================================================
README_DATA = b"ext2 filesystem created from scratch for this task.\n"

_csv_rows = ["id,value,square"] + [f"{i},{i},{i*i}" for i in range(1, 11)]
MEAS_CSV_DATA = ("\n".join(_csv_rows) + "\n").encode()

LARGE_BIN_SIZE   = 14336  # 14 * 1024
LARGE_BIN_DATA   = bytes([i % 251 for i in range(LARGE_BIN_SIZE)])
LARGE_BIN_NBLOCKS = 14

SETTINGS_DATA   = b"key=value\ndebug=false\ntimeout=30\n"
ACCESS_LOG_DATA = b"2024-01-01 00:00:00 GET /index.html 200\n"


# ============================================================
# Helpers
# ============================================================
def w32(buf, off, val):
    struct.pack_into("<I", buf, off, val & 0xFFFFFFFF)


def w16(buf, off, val):
    struct.pack_into("<H", buf, off, val & 0xFFFF)


def put_block(img, blk, data):
    off = blk * BLOCK_SIZE
    img[off:off + len(data)] = data


def build_dir_block(entries):
    """Build a 1024-byte directory block from (inode, name, filetype) tuples."""
    buf = bytearray(BLOCK_SIZE)
    pos = 0
    for idx, (ino, name, ft) in enumerate(entries):
        nb = name.encode("ascii")
        min_reclen = (8 + len(nb) + 3) & ~3  # 4-byte aligned minimum
        if idx < len(entries) - 1:
            reclen = min_reclen
        else:
            reclen = BLOCK_SIZE - pos          # last entry absorbs rest
        w32(buf, pos, ino)
        w16(buf, pos + 4, reclen)
        buf[pos + 6] = len(nb)
        buf[pos + 7] = ft
        buf[pos + 8:pos + 8 + len(nb)] = nb
        pos += reclen
    return buf


def write_inode(img, ino, mode, size, links, data_blocks, indirect=0):
    """Write one inode into the inode table.

    *data_blocks*: ALL data block numbers (first 12 in direct pointers,
    rest assumed to be referenced via the indirect block).
    *indirect*: block number of the singly-indirect block (0 = none).
    """
    off = BLK_ITABLE * BLOCK_SIZE + (ino - 1) * INODE_SIZE
    n_meta = 1 if indirect else 0
    sectors = (len(data_blocks) + n_meta) * (BLOCK_SIZE // 512)

    ibuf = bytearray(INODE_SIZE)
    w16(ibuf, 0, mode)
    w32(ibuf, 4, size)
    # Timestamps left as 0 — valid for ext2, fsck does not check values
    w16(ibuf, 26, links)       # i_links_count
    w32(ibuf, 28, sectors)     # i_blocks (512-byte sectors)
    for j, blk in enumerate(data_blocks[:12]):
        w32(ibuf, 40 + j * 4, blk)
    if indirect:
        w32(ibuf, 88, indirect)  # singly indirect pointer
    img[off:off + INODE_SIZE] = ibuf


# ============================================================
# Main
# ============================================================
def main():
    img = bytearray(IMAGE_SIZE)

    # ================================================================
    # SUPERBLOCK  (block 1, byte offset 1024)
    # ================================================================
    sb = bytearray(BLOCK_SIZE)
    w32(sb, 0,  INODES_COUNT)           # s_inodes_count
    w32(sb, 4,  TOTAL_BLOCKS)           # s_blocks_count
    w32(sb, 8,  0)                      # s_r_blocks_count
    w32(sb, 12, FREE_BLOCKS)            # s_free_blocks_count
    w32(sb, 16, FREE_INODES)            # s_free_inodes_count
    w32(sb, 20, S_FIRST_DATA_BLOCK)     # s_first_data_block
    w32(sb, 24, 0)                      # s_log_block_size (1024 << 0)
    w32(sb, 28, 0)                      # s_log_frag_size
    w32(sb, 32, BLOCKS_PER_GROUP)       # s_blocks_per_group
    w32(sb, 36, BLOCKS_PER_GROUP)       # s_frags_per_group
    w32(sb, 40, INODES_COUNT)           # s_inodes_per_group
    w16(sb, 54, 0xFFFF)                 # s_max_mnt_count (disable)
    w16(sb, 56, 0xEF53)                 # s_magic
    w16(sb, 58, 1)                      # s_state (EXT2_VALID_FS)
    w16(sb, 60, 1)                      # s_errors (EXT2_ERRORS_CONTINUE)
    w32(sb, 76, 1)                      # s_rev_level (EXT2_DYNAMIC_REV)
    w32(sb, 84, S_FIRST_INO)            # s_first_ino
    w16(sb, 88, INODE_SIZE)             # s_inode_size
    w32(sb, 96, FINCOMPAT_FILETYPE)     # s_feature_incompat
    vname = b"tbench-ext2"
    sb[120:120 + len(vname)] = vname    # s_volume_name (16 bytes max)
    img[1024:1024 + BLOCK_SIZE] = sb

    # ================================================================
    # BLOCK GROUP DESCRIPTOR TABLE  (block 2)
    # ================================================================
    bgd = bytearray(BLOCK_SIZE)
    w32(bgd, 0,  BLK_BBITMAP)          # bg_block_bitmap
    w32(bgd, 4,  BLK_IBITMAP)          # bg_inode_bitmap
    w32(bgd, 8,  BLK_ITABLE)           # bg_inode_table
    w16(bgd, 12, FREE_BLOCKS)          # bg_free_blocks_count
    w16(bgd, 14, FREE_INODES)          # bg_free_inodes_count
    w16(bgd, 16, USED_DIRS)            # bg_used_dirs_count
    put_block(img, BLK_BGDT, bgd)

    # ================================================================
    # BLOCK BITMAP  (block 3)
    # ================================================================
    # Bit N represents block (S_FIRST_DATA_BLOCK + N).
    # Block 0 (boot sector) is outside the group.
    bb = bytearray(BLOCK_SIZE)
    # Mark allocated blocks
    for blk in range(S_FIRST_DATA_BLOCK, LAST_USED_BLOCK + 1):
        bit = blk - S_FIRST_DATA_BLOCK
        bb[bit // 8] |= 1 << (bit % 8)
    # Padding: set bits for blocks beyond filesystem
    for bit in range(TRACKABLE, BLOCK_SIZE * 8):
        bb[bit // 8] |= 1 << (bit % 8)
    put_block(img, BLK_BBITMAP, bb)

    # ================================================================
    # INODE BITMAP  (block 4)
    # ================================================================
    # Bit N represents inode (N + 1).
    ib = bytearray(BLOCK_SIZE)
    for i in range(USED_INODES):
        ib[i // 8] |= 1 << (i % 8)
    # Padding for non-existent inodes
    for bit in range(INODES_COUNT, BLOCK_SIZE * 8):
        ib[bit // 8] |= 1 << (bit % 8)
    put_block(img, BLK_IBITMAP, ib)

    # ================================================================
    # INODE TABLE  (blocks 5-20)
    # ================================================================
    # Inodes 1, 3-10 are reserved; left zeroed (marked used in bitmap only).

    # Root directory: links = 2 (., ..) + 4 subdirectories = 6
    write_inode(img, INO_ROOT, 0o40755, BLOCK_SIZE, 6, [BLK_ROOT_DIR])

    # /lost+found: links = 2 (., ..)
    write_inode(img, INO_LOST_FOUND, 0o40700, BLOCK_SIZE, 2, [BLK_LOST_FOUND])

    # /README
    write_inode(img, INO_README, 0o100644, len(README_DATA), 1, [BLK_README])

    # /data/
    write_inode(img, INO_DATA_DIR, 0o40755, BLOCK_SIZE, 2, [BLK_DATA_DIR])

    # /data/measurements.csv
    write_inode(img, INO_MEAS_CSV, 0o100644, len(MEAS_CSV_DATA), 1, [BLK_MEAS_CSV])

    # /data/large.bin — 14 data blocks + 1 indirect block
    all_lb = BLK_LB_DIRECT + BLK_LB_EXTRA  # 14 data block numbers
    write_inode(img, INO_LARGE_BIN, 0o100644, LARGE_BIN_SIZE, 1,
                all_lb, indirect=BLK_LB_INDIRECT)

    # /config/
    write_inode(img, INO_CONFIG_DIR, 0o40755, BLOCK_SIZE, 2, [BLK_CONFIG_DIR])

    # /config/settings.conf (and settings.bak via hard link) — links = 2
    write_inode(img, INO_SETTINGS, 0o100644, len(SETTINGS_DATA), 2, [BLK_SETTINGS])

    # /logs/
    write_inode(img, INO_LOGS_DIR, 0o40755, BLOCK_SIZE, 2, [BLK_LOGS_DIR])

    # /logs/access.log
    write_inode(img, INO_ACCESS_LOG, 0o100644, len(ACCESS_LOG_DATA), 1, [BLK_ACCESS_LOG])

    # ================================================================
    # DIRECTORY DATA BLOCKS
    # ================================================================

    # /  (root directory)
    put_block(img, BLK_ROOT_DIR, build_dir_block([
        (INO_ROOT,       ".",          FT_DIR),
        (INO_ROOT,       "..",         FT_DIR),
        (INO_LOST_FOUND, "lost+found", FT_DIR),
        (INO_README,     "README",     FT_REG),
        (INO_DATA_DIR,   "data",       FT_DIR),
        (INO_CONFIG_DIR, "config",     FT_DIR),
        (INO_LOGS_DIR,   "logs",       FT_DIR),
    ]))

    # /lost+found
    put_block(img, BLK_LOST_FOUND, build_dir_block([
        (INO_LOST_FOUND, ".",  FT_DIR),
        (INO_ROOT,       "..", FT_DIR),
    ]))

    # /data
    put_block(img, BLK_DATA_DIR, build_dir_block([
        (INO_DATA_DIR,  ".",                FT_DIR),
        (INO_ROOT,      "..",               FT_DIR),
        (INO_MEAS_CSV,  "measurements.csv", FT_REG),
        (INO_LARGE_BIN, "large.bin",        FT_REG),
    ]))

    # /config — settings.bak is a hard link (same inode as settings.conf)
    put_block(img, BLK_CONFIG_DIR, build_dir_block([
        (INO_CONFIG_DIR, ".",             FT_DIR),
        (INO_ROOT,       "..",            FT_DIR),
        (INO_SETTINGS,   "settings.conf", FT_REG),
        (INO_SETTINGS,   "settings.bak",  FT_REG),  # hard link!
    ]))

    # /logs
    put_block(img, BLK_LOGS_DIR, build_dir_block([
        (INO_LOGS_DIR,   ".",          FT_DIR),
        (INO_ROOT,       "..",         FT_DIR),
        (INO_ACCESS_LOG, "access.log", FT_REG),
    ]))

    # ================================================================
    # FILE DATA BLOCKS
    # ================================================================
    put_block(img, BLK_README, README_DATA)
    put_block(img, BLK_MEAS_CSV, MEAS_CSV_DATA)

    # large.bin — 12 direct blocks + 2 blocks via indirect
    for i in range(12):
        s = i * BLOCK_SIZE
        put_block(img, BLK_LB_DIRECT[i], LARGE_BIN_DATA[s:s + BLOCK_SIZE])
    for i in range(2):
        s = (12 + i) * BLOCK_SIZE
        put_block(img, BLK_LB_EXTRA[i], LARGE_BIN_DATA[s:s + BLOCK_SIZE])

    # Singly indirect block: pointers to the 2 overflow data blocks
    ind = bytearray(BLOCK_SIZE)
    for i, blk in enumerate(BLK_LB_EXTRA):
        w32(ind, i * 4, blk)
    put_block(img, BLK_LB_INDIRECT, ind)

    put_block(img, BLK_SETTINGS, SETTINGS_DATA)
    put_block(img, BLK_ACCESS_LOG, ACCESS_LOG_DATA)

    # ================================================================
    # WRITE IMAGE
    # ================================================================
    with open("/app/ext2.img", "wb") as f:
        f.write(img)
    print(f"Wrote {len(img)} bytes to /app/ext2.img")


if __name__ == "__main__":
    main()
