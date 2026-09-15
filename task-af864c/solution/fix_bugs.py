#!/usr/bin/env python3
"""
Diagnose and fix the three bugs in /app/build_ext2.py.

Bug analysis (from fsck.ext2 -fn output):
  1. "Block bitmap differences: +40" — block 40 (the singly indirect block
     for large.bin) is allocated but LAST_USED_BLOCK only counts up to 39
     (the last data block).  Fix: set LAST_USED_BLOCK = BLK_INDIRECT so the
     bitmap and free-count variables include the indirect block.

  2. "Inode 15, i_blocks is 28, should be 30" — i_blocks counts 512-byte
     sectors for ALL allocated blocks including indirect blocks.
     14 data + 1 indirect = 15 blocks x 2 = 30 sectors.

  3. "Inode 2 ref count is 3, should be 4" — root directory link count
     should be 2 (for . and ..) + number of subdirectories.  Root has two
     subdirectories (lost+found AND data), not one.
"""


with open("/app/build_ext2.py", "r") as f:
    code = f.read()

# Fix 1: Include the indirect block in allocation tracking.
# This single change corrects the block bitmap and the derived
# ALLOCATED_BLOCK_COUNT / FREE_BLOCK_COUNT variables.
code = code.replace(
    "LAST_USED_BLOCK = BLK_LARGE_START + LARGE_BIN_NBLKS - 1   # last data block of large.bin",
    "LAST_USED_BLOCK = BLK_INDIRECT   # include the indirect block for large.bin",
)

# Fix 2: Include the indirect block in the i_blocks sector count.
code = code.replace(
    "i_blocks=LARGE_BIN_NBLKS * (BLOCK_SIZE // 512),",
    "i_blocks=(LARGE_BIN_NBLKS + 1) * (BLOCK_SIZE // 512),  # +1 for indirect block",
)

# Fix 3: Correct root directory link count (2 subdirs, not 1).
code = code.replace(
    "# links = 2 (for \".\" and \"..\") + number of subdirectories (lost+found)\n"
    "    write_inode(img, INO_ROOT, mode=0o40755, size=BLOCK_SIZE,\n"
    "                links=3, i_blocks=2, direct_blks=[BLK_ROOT_DIR])",
    "# links = 2 (for \".\" and \"..\") + number of subdirectories (lost+found, data)\n"
    "    write_inode(img, INO_ROOT, mode=0o40755, size=BLOCK_SIZE,\n"
    "                links=4, i_blocks=2, direct_blks=[BLK_ROOT_DIR])",
)

with open("/app/build_ext2.py", "w") as f:
    f.write(code)

print("All 3 bugs fixed in build_ext2.py")
