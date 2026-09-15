#!/usr/bin/env python3
"""Generate a corrupted xv6 file system image for the fsck task.

Creates a valid xv6 FS image with several planted corruptions:
  1. Uncommitted log transaction (create recovered.txt)
  2. Orphaned inodes (inodes 10, 11 with nlink=0)
  3. Bitmap inconsistency (block 300 leaked, block 51 not marked)
  4. Inode size error (inode 6 size=5000 but only 3 blocks)
"""
import struct
import os

# xv6 file system constants
BSIZE = 1024
FSSIZE = 1000
NINODES = 200
NLOG = 30
FSMAGIC = 0x10203040
NDIRECT = 12
T_DIR = 1
T_FILE = 2
DIRSIZ = 14
IPB = BSIZE // 64   # 16
BPB = BSIZE * 8     # 8192

# Layout
LOGSTART = 2
INODESTART = LOGSTART + NLOG           # 32
NINODEBLOCKS = NINODES // IPB + 1      # 13
BMAPSTART = INODESTART + NINODEBLOCKS  # 45
NBITMAP = FSSIZE // BPB + 1            # 1
NMETA = 2 + NLOG + NINODEBLOCKS + NBITMAP  # 46
NBLOCKS = FSSIZE - NMETA               # 954

# Data block assignments
BLK_ROOTDIR   = 46
BLK_HELLO     = 47
BLK_DATABIN_0 = 48
BLK_DATABIN_1 = 49
BLK_SUBDIR    = 50
BLK_README    = 51
BLK_LARGE_0   = 52
BLK_LARGE_1   = 53
BLK_LARGE_2   = 54
BLK_RECOVERED = 55
BLK_ORPHAN10  = 60
BLK_ORPHAN11  = 61


class DiskImage:
    def __init__(self):
        self.data = bytearray(FSSIZE * BSIZE)

    def write_block(self, bno, block_data):
        off = bno * BSIZE
        n = min(len(block_data), BSIZE)
        self.data[off:off + n] = block_data[:n]

    def read_block(self, bno):
        off = bno * BSIZE
        return bytes(self.data[off:off + BSIZE])

    def pack_dinode(self, dtype, major, minor, nlink, size, addrs):
        """Pack a 64-byte on-disk inode."""
        d = struct.pack('<hhhhI', dtype, major, minor, nlink, size)
        for i in range(NDIRECT + 1):
            d += struct.pack('<I', addrs[i] if i < len(addrs) else 0)
        assert len(d) == 64
        return d

    def write_inode(self, inum, dtype, major, minor, nlink, size, addrs):
        blk = inum // IPB + INODESTART
        off = blk * BSIZE + (inum % IPB) * 64
        self.data[off:off + 64] = self.pack_dinode(
            dtype, major, minor, nlink, size, addrs)

    def pack_dirent(self, inum, name):
        """Pack a 16-byte directory entry."""
        nb = name.encode('ascii')[:DIRSIZ].ljust(DIRSIZ, b'\x00')
        return struct.pack('<H', inum) + nb

    def mark_bitmap(self, bno):
        base = (bno // BPB + BMAPSTART) * BSIZE
        self.data[base + (bno % BPB) // 8] |= 1 << (bno % 8)

    def save(self, path):
        with open(path, 'wb') as f:
            f.write(self.data)


def main():
    img = DiskImage()

    # --- Superblock (block 1) ---
    sb = struct.pack('<IIIIIIII',
                     FSMAGIC, FSSIZE, NBLOCKS, NINODES,
                     NLOG, LOGSTART, INODESTART, BMAPSTART)
    img.write_block(1, sb)

    # Mark all metadata blocks in bitmap (blocks 0..NMETA-1)
    for b in range(NMETA):
        img.mark_bitmap(b)

    # ========== Valid file system content ==========

    # Root directory (inode 1): 6 entries before crash
    root_ents = b''
    root_ents += img.pack_dirent(1, '.')
    root_ents += img.pack_dirent(1, '..')
    root_ents += img.pack_dirent(2, 'hello.txt')
    root_ents += img.pack_dirent(3, 'data.bin')
    root_ents += img.pack_dirent(4, 'subdir')
    root_ents += img.pack_dirent(6, 'large.txt')
    img.write_block(BLK_ROOTDIR, root_ents)
    img.mark_bitmap(BLK_ROOTDIR)
    # nlink=3: root/., root/.., subdir/..
    img.write_inode(1, T_DIR, 0, 0, 3, len(root_ents), [BLK_ROOTDIR])

    # hello.txt (inode 2)
    hello = b'Hello, xv6 world!\n'
    img.write_block(BLK_HELLO, hello)
    img.mark_bitmap(BLK_HELLO)
    img.write_inode(2, T_FILE, 0, 0, 1, len(hello), [BLK_HELLO])

    # data.bin (inode 3): 1500 bytes across 2 blocks
    databin = bytes([i % 256 for i in range(1500)])
    img.write_block(BLK_DATABIN_0, databin[:BSIZE])
    img.write_block(BLK_DATABIN_1, databin[BSIZE:])
    img.mark_bitmap(BLK_DATABIN_0)
    img.mark_bitmap(BLK_DATABIN_1)
    img.write_inode(3, T_FILE, 0, 0, 1, len(databin),
                    [BLK_DATABIN_0, BLK_DATABIN_1])

    # subdir/ (inode 4)
    sub_ents = b''
    sub_ents += img.pack_dirent(4, '.')
    sub_ents += img.pack_dirent(1, '..')
    sub_ents += img.pack_dirent(5, 'readme.txt')
    img.write_block(BLK_SUBDIR, sub_ents)
    img.mark_bitmap(BLK_SUBDIR)
    # nlink=2: root/subdir, subdir/.
    img.write_inode(4, T_DIR, 0, 0, 2, len(sub_ents), [BLK_SUBDIR])

    # readme.txt (inode 5) -- CORRUPTION: bitmap bit intentionally NOT set
    readme = b'This is a readme.\n'
    img.write_block(BLK_README, readme)
    # img.mark_bitmap(BLK_README)  # <-- intentionally omitted
    img.write_inode(5, T_FILE, 0, 0, 1, len(readme), [BLK_README])

    # large.txt (inode 6) -- CORRUPTION: size=5000 but only 3 blocks (3072 max)
    large = bytes([((i * 7 + 13) % 256) for i in range(3 * BSIZE)])
    img.write_block(BLK_LARGE_0, large[:BSIZE])
    img.write_block(BLK_LARGE_1, large[BSIZE:2 * BSIZE])
    img.write_block(BLK_LARGE_2, large[2 * BSIZE:3 * BSIZE])
    img.mark_bitmap(BLK_LARGE_0)
    img.mark_bitmap(BLK_LARGE_1)
    img.mark_bitmap(BLK_LARGE_2)
    img.write_inode(6, T_FILE, 0, 0, 1, 5000,
                    [BLK_LARGE_0, BLK_LARGE_1, BLK_LARGE_2])

    # recovered.txt data -- written to disk but not committed yet
    recovered = b'Log recovery successful!\n'
    img.write_block(BLK_RECOVERED, recovered)
    img.mark_bitmap(BLK_RECOVERED)
    # Inode 7 stays type=0 (uncommitted -- will be set by log replay)

    # ========== Corruptions ==========

    # Orphaned inode 10 (type=2, nlink=0, has data)
    orph10 = b'Orphaned file 10 data\n'
    img.write_block(BLK_ORPHAN10, orph10)
    img.mark_bitmap(BLK_ORPHAN10)
    img.write_inode(10, T_FILE, 0, 0, 0, len(orph10), [BLK_ORPHAN10])

    # Orphaned inode 11 (type=2, nlink=0, has data)
    orph11 = b'Orphaned file 11 data\n'
    img.write_block(BLK_ORPHAN11, orph11)
    img.mark_bitmap(BLK_ORPHAN11)
    img.write_inode(11, T_FILE, 0, 0, 0, len(orph11), [BLK_ORPHAN11])

    # Leaked block: block 300 marked used but unreferenced
    img.mark_bitmap(300)

    # ========== Write-ahead log (uncommitted transaction) ==========
    # Represents an interrupted "create recovered.txt" operation.
    # Log entry 0 -> inode block 32 (updates inodes 1 and 7)
    # Log entry 1 -> root dir block 46 (adds recovered.txt entry)

    # Build post-commit inode block 32
    inode_blk = bytearray(img.read_block(INODESTART))
    # Update inode 1: expanded root directory size
    new_root_size = len(root_ents) + 16  # one more dirent
    off1 = (1 % IPB) * 64
    inode_blk[off1:off1 + 64] = img.pack_dinode(
        T_DIR, 0, 0, 3, new_root_size, [BLK_ROOTDIR])
    # Update inode 7: new file
    off7 = (7 % IPB) * 64
    inode_blk[off7:off7 + 64] = img.pack_dinode(
        T_FILE, 0, 0, 1, len(recovered), [BLK_RECOVERED])

    # Build post-commit root dir block
    rootdir_blk = bytearray(img.read_block(BLK_ROOTDIR))
    rootdir_blk[len(root_ents):len(root_ents) + 16] = \
        img.pack_dirent(7, 'recovered.txt')

    # Write log data blocks
    img.write_block(LOGSTART + 1, bytes(inode_blk))   # log slot 0
    img.write_block(LOGSTART + 2, bytes(rootdir_blk))  # log slot 1

    # Write log header: n=2, destinations = [block 32, block 46]
    hdr = struct.pack('<iii', 2, INODESTART, BLK_ROOTDIR)
    img.write_block(LOGSTART, hdr)

    # ========== Save ==========
    os.makedirs('/app', exist_ok=True)
    img.save('/app/fs.img')
    print('Generated corrupted xv6 filesystem image at /app/fs.img')


if __name__ == '__main__':
    main()
