#!/usr/bin/env python3
"""Generate a minimal valid xv6 reference filesystem image at /app/reference.img."""
import struct
import os

BSIZE = 1024
IPB = 16
BPB = 8192
FSMAGIC = 0x10203040
DIRSIZ = 14
ROOTINO = 1
T_DIR = 1
T_FILE = 2

fssize = 100
ninodes = 32
nlog = 10
logstart = 2
inodestart = logstart + nlog            # 12
niblocks = (ninodes + IPB - 1) // IPB   # 2
bmapstart = inodestart + niblocks       # 14
nbmapblocks = (fssize + BPB - 1) // BPB  # 1
datastart = bmapstart + nbmapblocks     # 15
nblocks = fssize - datastart            # 85

data = bytearray(fssize * BSIZE)

# Superblock at block 1
struct.pack_into('<IIIIIIII', data, BSIZE,
                 FSMAGIC, fssize, nblocks, ninodes,
                 nlog, logstart, inodestart, bmapstart)


def set_bitmap(block):
    bit = block % BPB
    off = (bmapstart + block // BPB) * BSIZE + bit // 8
    data[off] |= 1 << (bit % 8)


def make_dirent(inum, name):
    nb = name.encode('ascii')[:DIRSIZ].ljust(DIRSIZ, b'\x00')
    return struct.pack('<H', inum) + nb


# Mark all metadata blocks in bitmap
for b in range(datastart):
    set_bitmap(b)

# Allocate root data block (first data block)
root_blk = datastart
set_bitmap(root_blk)

# Root directory entries: "." and ".."
data[root_blk * BSIZE:root_blk * BSIZE + 32] = (
    make_dirent(ROOTINO, '.') + make_dirent(ROOTINO, '..')
)

# Allocate a file data block
file_blk = datastart + 1
set_bitmap(file_blk)
file_content = b'Hello from xv6 reference image.\n'
data[file_blk * BSIZE:file_blk * BSIZE + len(file_content)] = file_content

# File inode (inum=2): type=T_FILE, nlink=1
file_inum = 2
fipos = (file_inum // IPB + inodestart) * BSIZE + (file_inum % IPB) * 64
struct.pack_into('<hhhhI', data, fipos, T_FILE, 0, 0, 1, len(file_content))
struct.pack_into('<I', data, fipos + 12, file_blk)

# Add "hello" entry to root directory
hello_entry = make_dirent(file_inum, 'hello')
data[root_blk * BSIZE + 32:root_blk * BSIZE + 48] = hello_entry
root_size = 48  # 3 entries x 16 bytes

# Root inode (inum=1): type=T_DIR, nlink=1 (from own ".."), size=48
ipos = (ROOTINO // IPB + inodestart) * BSIZE + (ROOTINO % IPB) * 64
struct.pack_into('<hhhhI', data, ipos, T_DIR, 0, 0, 1, root_size)
struct.pack_into('<I', data, ipos + 12, root_blk)

os.makedirs('/app', exist_ok=True)
with open('/app/reference.img', 'wb') as f:
    f.write(data)
