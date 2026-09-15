#!/usr/bin/env python3
"""Generate corrupted xv6 filesystem images for consistency analysis."""
import struct
import os

BSIZE = 1024
NDIRECT = 12
NINDIRECT = BSIZE // 4
IPB = BSIZE // 64
BPB = BSIZE * 8
T_DIR = 1
T_FILE = 2
FSMAGIC = 0x10203040
DIRSIZ = 14
ROOTINO = 1


class XV6Image:
    """Creates xv6 filesystem images with optional corruptions."""

    def __init__(self, fssize=100, ninodes=32):
        self.fssize = fssize
        self.ninodes = ninodes
        self.nlog = 10

        niblocks = (ninodes + IPB - 1) // IPB
        nbmapblocks = (fssize + BPB - 1) // BPB

        self.logstart = 2
        self.inodestart = self.logstart + self.nlog
        self.bmapstart = self.inodestart + niblocks
        self.datastart = self.bmapstart + nbmapblocks
        self.nblocks = fssize - self.datastart

        self.data = bytearray(fssize * BSIZE)
        self.next_data_block = self.datastart
        self.next_inode = ROOTINO + 1

        struct.pack_into('<IIIIIIII', self.data, BSIZE,
                         FSMAGIC, fssize, self.nblocks, ninodes,
                         self.nlog, self.logstart, self.inodestart, self.bmapstart)

        for b in range(self.datastart):
            self._set_bitmap(b)

        root_block = self._alloc_block()
        dot = self._make_dirent(ROOTINO, '.')
        dotdot = self._make_dirent(ROOTINO, '..')
        self._write_at(root_block * BSIZE, dot + dotdot)

        addrs = [0] * 13
        addrs[0] = root_block
        self._write_inode(ROOTINO, T_DIR, 0, 0, 1, 32, addrs)

    def _set_bitmap(self, block):
        bit = block % BPB
        idx = block // BPB
        off = (self.bmapstart + idx) * BSIZE + bit // 8
        self.data[off] |= (1 << (bit % 8))

    def _clear_bitmap(self, block):
        bit = block % BPB
        idx = block // BPB
        off = (self.bmapstart + idx) * BSIZE + bit // 8
        self.data[off] &= ~(1 << (bit % 8))

    def _write_at(self, offset, payload):
        self.data[offset:offset + len(payload)] = payload

    def _make_dirent(self, inum, name):
        nb = name.encode('ascii')[:DIRSIZ].ljust(DIRSIZ, b'\x00')
        return struct.pack('<H', inum) + nb

    def _write_inode(self, inum, typ, major, minor, nlink, size, addrs):
        block = inum // IPB + self.inodestart
        off = (inum % IPB) * 64
        pos = block * BSIZE + off
        struct.pack_into('<hhhhI', self.data, pos, typ, major, minor, nlink, size)
        for i in range(13):
            struct.pack_into('<I', self.data, pos + 12 + i * 4, addrs[i])

    def _read_inode_raw(self, inum):
        block = inum // IPB + self.inodestart
        off = (inum % IPB) * 64
        pos = block * BSIZE + off
        typ, major, minor, nlink, size = struct.unpack_from('<hhhhI', self.data, pos)
        addrs = [struct.unpack_from('<I', self.data, pos + 12 + i * 4)[0]
                 for i in range(13)]
        return typ, major, minor, nlink, size, addrs

    def _alloc_block(self):
        b = self.next_data_block
        if b >= self.fssize:
            raise RuntimeError("out of blocks")
        self.next_data_block += 1
        self._set_bitmap(b)
        return b

    def _alloc_inode(self):
        inum = self.next_inode
        self.next_inode += 1
        return inum

    def _add_dir_entry(self, parent_inum, name, target_inum):
        t, maj, mi, nl, sz, addrs = self._read_inode_raw(parent_inum)
        entry = self._make_dirent(target_inum, name)
        block_idx = sz // BSIZE
        offset_in_block = sz % BSIZE
        if addrs[block_idx] == 0:
            addrs[block_idx] = self._alloc_block()
        pos = addrs[block_idx] * BSIZE + offset_in_block
        self.data[pos:pos + 16] = entry
        sz += 16
        self._write_inode(parent_inum, t, maj, mi, nl, sz, addrs)

    def add_file(self, name, content_size, parent_inum=ROOTINO):
        inum = self._alloc_inode()
        addrs = [0] * 13
        blocks = []
        remaining = content_size
        bi = 0
        while remaining > 0 and bi < NDIRECT:
            b = self._alloc_block()
            fill = bytes([(inum + bi) & 0xFF] * min(remaining, BSIZE))
            self._write_at(b * BSIZE, fill)
            addrs[bi] = b
            blocks.append(b)
            remaining -= BSIZE
            bi += 1
        self._write_inode(inum, T_FILE, 0, 0, 1, content_size, addrs)
        self._add_dir_entry(parent_inum, name, inum)
        return inum, blocks

    def add_dir(self, name, parent_inum=ROOTINO):
        inum = self._alloc_inode()
        db = self._alloc_block()
        dot = self._make_dirent(inum, '.')
        dotdot = self._make_dirent(parent_inum, '..')
        self._write_at(db * BSIZE, dot + dotdot)
        addrs = [0] * 13
        addrs[0] = db
        self._write_inode(inum, T_DIR, 0, 0, 1, 32, addrs)
        self._add_dir_entry(parent_inum, name, inum)
        t, maj, mi, nl, sz, a = self._read_inode_raw(parent_inum)
        self._write_inode(parent_inum, t, maj, mi, nl + 1, sz, a)
        return inum

    def save(self, path):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, 'wb') as f:
            f.write(self.data)


outdir = '/app/corrupted'
os.makedirs(outdir, exist_ok=True)

# sample_a: one bitmap-related corruption
img = XV6Image()
inum, blocks = img.add_file('data', 500)
img._clear_bitmap(blocks[0])
img.save(os.path.join(outdir, 'sample_a.img'))

# sample_b: another bitmap-related corruption
img = XV6Image()
img.add_file('notes', 800)
img._set_bitmap(img.fssize - 1)
img.save(os.path.join(outdir, 'sample_b.img'))

# sample_c: inode metadata corruption
img = XV6Image()
inum, _ = img.add_file('report', 600)
t, maj, mi, _, sz, addrs = img._read_inode_raw(inum)
img._write_inode(inum, t, maj, mi, 4, sz, addrs)
img.save(os.path.join(outdir, 'sample_c.img'))

# sample_d: directory structure corruption
img = XV6Image()
img.add_file('legit', 500)
oinum = img._alloc_inode()
oa = [0] * 13
ob = img._alloc_block()
img._write_at(ob * BSIZE, bytes([0xBB] * 100))
oa[0] = ob
img._write_inode(oinum, T_FILE, 0, 0, 1, 100, oa)
img.save(os.path.join(outdir, 'sample_d.img'))

# sample_e: block sharing corruption
img = XV6Image()
inum1, blocks1 = img.add_file('orig', 500)
inum2 = img._alloc_inode()
da = [0] * 13
da[0] = blocks1[0]
img._write_inode(inum2, T_FILE, 0, 0, 1, BSIZE, da)
img._add_dir_entry(ROOTINO, 'copy', inum2)
img.save(os.path.join(outdir, 'sample_e.img'))

# sample_f: invalid block pointer corruption
img = XV6Image()
binum = img._alloc_inode()
ba = [0] * 13
gb = img._alloc_block()
img._write_at(gb * BSIZE, bytes([0x42] * BSIZE))
ba[0] = gb
ba[1] = img.fssize + 50
img._write_inode(binum, T_FILE, 0, 0, 1, BSIZE * 2, ba)
img._add_dir_entry(ROOTINO, 'broken', binum)
img.save(os.path.join(outdir, 'sample_f.img'))

# sample_g: multiple simultaneous corruptions
img = XV6Image()
inum1, blocks1 = img.add_file('file1', 500)
inum2, blocks2 = img.add_file('file2', 1000)
img.add_dir('mydir')
img._clear_bitmap(blocks1[0])
img._set_bitmap(img.fssize - 3)
t, maj, mi, _, sz, addrs = img._read_inode_raw(inum2)
img._write_inode(inum2, t, maj, mi, 5, sz, addrs)
img.save(os.path.join(outdir, 'sample_g.img'))
