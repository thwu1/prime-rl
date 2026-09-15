#!/usr/bin/env python3

"""
xv6 file system checker and recovery tool.

Performs: log replay, orphan cleanup, bitmap consistency fix,
inode size validation, and recovered file detection.
"""

import struct
import json

# xv6 file system constants
BSIZE = 1024
FSMAGIC = 0x10203040
NDIRECT = 12
NINDIRECT = BSIZE // 4   # 256
T_DIR = 1
T_FILE = 2
T_DEVICE = 3
DIRSIZ = 14
IPB = BSIZE // 64        # 16
BPB = BSIZE * 8          # 8192


class Xv6FS:
    """In-memory representation of an xv6 file system image."""

    def __init__(self, path):
        with open(path, 'rb') as f:
            self.data = bytearray(f.read())
        self._parse_sb()

    def _parse_sb(self):
        vals = struct.unpack_from('<IIIIIIII', self.data, BSIZE)
        self.sb = dict(zip(
            ('magic', 'size', 'nblocks', 'ninodes',
             'nlog', 'logstart', 'inodestart', 'bmapstart'),
            vals))
        assert self.sb['magic'] == FSMAGIC, 'Bad FS magic'
        ninodeblocks = self.sb['ninodes'] // IPB + 1
        nbitmap = self.sb['size'] // BPB + 1
        self.nmeta = 2 + self.sb['nlog'] + ninodeblocks + nbitmap

    # ---- inode operations ----

    def _ioff(self, inum):
        """Byte offset of inode inum in the image."""
        blk = inum // IPB + self.sb['inodestart']
        return blk * BSIZE + (inum % IPB) * 64

    def read_inode(self, inum):
        off = self._ioff(inum)
        t, maj, mi, nl, sz = struct.unpack_from('<hhhhI', self.data, off)
        addrs = [struct.unpack_from('<I', self.data, off + 12 + i * 4)[0]
                 for i in range(NDIRECT + 1)]
        return {'type': t, 'major': maj, 'minor': mi,
                'nlink': nl, 'size': sz, 'addrs': addrs}

    def write_inode(self, inum, inode):
        off = self._ioff(inum)
        struct.pack_into('<hhhhI', self.data, off,
                         inode['type'], inode['major'], inode['minor'],
                         inode['nlink'], inode['size'])
        for i in range(NDIRECT + 1):
            struct.pack_into('<I', self.data, off + 12 + i * 4,
                             inode['addrs'][i])

    # ---- bitmap operations ----

    def _bmap_pos(self, bno):
        base = (bno // BPB + self.sb['bmapstart']) * BSIZE
        return base + (bno % BPB) // 8, 1 << (bno % 8)

    def is_marked(self, bno):
        pos, bit = self._bmap_pos(bno)
        return bool(self.data[pos] & bit)

    def mark(self, bno):
        pos, bit = self._bmap_pos(bno)
        self.data[pos] |= bit

    def clear(self, bno):
        pos, bit = self._bmap_pos(bno)
        self.data[pos] &= ~bit

    # ---- block helpers ----

    def all_blocks(self, inode):
        """All block numbers referenced by an inode (data + indirect)."""
        blks = set()
        for i in range(NDIRECT):
            if inode['addrs'][i]:
                blks.add(inode['addrs'][i])
        if inode['addrs'][NDIRECT]:
            ib = inode['addrs'][NDIRECT]
            blks.add(ib)
            off = ib * BSIZE
            for i in range(NINDIRECT):
                a = struct.unpack_from('<I', self.data, off + i * 4)[0]
                if a:
                    blks.add(a)
        return blks

    def count_data_blocks(self, inode):
        """Count data blocks (excluding the indirect block itself)."""
        n = sum(1 for i in range(NDIRECT) if inode['addrs'][i])
        if inode['addrs'][NDIRECT]:
            off = inode['addrs'][NDIRECT] * BSIZE
            for i in range(NINDIRECT):
                if struct.unpack_from('<I', self.data, off + i * 4)[0]:
                    n += 1
        return n

    # ---- directory helpers ----

    def read_dirents(self, block_addr, nbytes):
        entries = []
        off = block_addr * BSIZE
        for i in range(min(nbytes, BSIZE) // 16):
            inum = struct.unpack_from('<H', self.data, off + i * 16)[0]
            raw = self.data[off + i * 16 + 2: off + i * 16 + 16]
            name = raw.split(b'\x00')[0].decode('ascii', errors='replace')
            entries.append((inum, name))
        return entries

    def reachable_inodes(self):
        """BFS/DFS from root inode 1; return set of reachable inums."""
        seen = set()

        def walk(inum):
            if inum in seen or inum == 0:
                return
            seen.add(inum)
            inode = self.read_inode(inum)
            if inode['type'] != T_DIR:
                return
            rem = inode['size']
            for i in range(NDIRECT):
                if not inode['addrs'][i] or rem <= 0:
                    break
                for einum, ename in self.read_dirents(
                        inode['addrs'][i], min(BSIZE, rem)):
                    if einum and ename not in ('.', '..'):
                        walk(einum)
                rem -= BSIZE
            # Handle indirect directory blocks (unlikely but safe)
            if rem > 0 and inode['addrs'][NDIRECT]:
                ioff = inode['addrs'][NDIRECT] * BSIZE
                for j in range(NINDIRECT):
                    if rem <= 0:
                        break
                    a = struct.unpack_from('<I', self.data, ioff + j * 4)[0]
                    if not a:
                        break
                    for einum, ename in self.read_dirents(
                            a, min(BSIZE, rem)):
                        if einum and ename not in ('.', '..'):
                            walk(einum)
                    rem -= BSIZE

        walk(1)
        return seen

    def find_name(self, target_inum):
        """Search all directories for an entry pointing to target_inum."""
        for inum in range(1, self.sb['ninodes']):
            inode = self.read_inode(inum)
            if inode['type'] != T_DIR:
                continue
            rem = inode['size']
            for i in range(NDIRECT):
                if not inode['addrs'][i] or rem <= 0:
                    break
                for einum, ename in self.read_dirents(
                        inode['addrs'][i], min(BSIZE, rem)):
                    if einum == target_inum and ename not in ('.', '..'):
                        return ename
                rem -= BSIZE
        return None

    def read_file(self, inode):
        """Read file content from data blocks."""
        parts = []
        rem = inode['size']
        for i in range(NDIRECT):
            if not inode['addrs'][i] or rem <= 0:
                break
            off = inode['addrs'][i] * BSIZE
            chunk = min(BSIZE, rem)
            parts.append(bytes(self.data[off:off + chunk]))
            rem -= chunk
        if rem > 0 and inode['addrs'][NDIRECT]:
            ioff = inode['addrs'][NDIRECT] * BSIZE
            for i in range(NINDIRECT):
                if rem <= 0:
                    break
                a = struct.unpack_from('<I', self.data, ioff + i * 4)[0]
                if not a:
                    break
                off = a * BSIZE
                chunk = min(BSIZE, rem)
                parts.append(bytes(self.data[off:off + chunk]))
                rem -= chunk
        return b''.join(parts)

    # ---- log operations ----

    def replay_log(self):
        """Replay WAL. Returns number of entries replayed."""
        hoff = self.sb['logstart'] * BSIZE
        n = struct.unpack_from('<i', self.data, hoff)[0]
        if n <= 0:
            return 0
        dsts = [struct.unpack_from('<i', self.data, hoff + 4 + i * 4)[0]
                for i in range(n)]
        for i in range(n):
            src = (self.sb['logstart'] + 1 + i) * BSIZE
            dst = dsts[i] * BSIZE
            self.data[dst:dst + BSIZE] = self.data[src:src + BSIZE]
        # Clear log header
        struct.pack_into('<i', self.data, hoff, 0)
        return n

    def save(self, path):
        with open(path, 'wb') as f:
            f.write(self.data)


def main():
    fs = Xv6FS('/app/fs.img')

    report = {
        'log_entries_replayed': 0,
        'orphaned_inodes': [],
        'bitmap_errors': {
            'marked_used_but_free': [],
            'marked_free_but_used': []
        },
        'size_errors': [],
        'recovered_files': {}
    }

    # --- 1. Snapshot pre-replay inode state ---
    pre_live = set()
    for i in range(1, fs.sb['ninodes']):
        if fs.read_inode(i)['type'] != 0:
            pre_live.add(i)

    # --- 2. Replay write-ahead log ---
    nr = fs.replay_log()
    report['log_entries_replayed'] = nr

    # --- 3. Detect recovered files ---
    if nr > 0:
        for i in range(1, fs.sb['ninodes']):
            inode = fs.read_inode(i)
            if inode['type'] == T_FILE and i not in pre_live:
                name = fs.find_name(i)
                if name:
                    content = fs.read_file(inode)
                    report['recovered_files'][name] = \
                        content.decode('ascii', errors='replace')

    # --- 4. Fix inode size errors ---
    for i in range(1, fs.sb['ninodes']):
        inode = fs.read_inode(i)
        if inode['type'] not in (T_FILE, T_DIR):
            continue
        cap = fs.count_data_blocks(inode) * BSIZE
        if inode['size'] > cap:
            report['size_errors'].append({
                'inum': i,
                'reported_size': inode['size'],
                'correct_size': cap
            })
            inode['size'] = cap
            fs.write_inode(i, inode)

    # --- 5. Find and clean orphaned inodes ---
    reachable = fs.reachable_inodes()
    for i in range(1, fs.sb['ninodes']):
        inode = fs.read_inode(i)
        if inode['type'] != 0 and i not in reachable:
            report['orphaned_inodes'].append(i)
            # Free data blocks in bitmap
            for b in fs.all_blocks(inode):
                if b >= fs.nmeta:
                    fs.clear(b)
            # Zero the inode
            zero = {'type': 0, 'major': 0, 'minor': 0,
                    'nlink': 0, 'size': 0,
                    'addrs': [0] * (NDIRECT + 1)}
            fs.write_inode(i, zero)
    report['orphaned_inodes'].sort()

    # --- 6. Fix bitmap consistency ---
    referenced = set(range(fs.nmeta))  # metadata always referenced
    for i in range(1, fs.sb['ninodes']):
        inode = fs.read_inode(i)
        if inode['type'] != 0:
            referenced.update(fs.all_blocks(inode))

    for b in range(fs.sb['size']):
        marked = fs.is_marked(b)
        used = b in referenced
        if marked and not used and b >= fs.nmeta:
            report['bitmap_errors']['marked_used_but_free'].append(b)
            fs.clear(b)
        elif not marked and used:
            report['bitmap_errors']['marked_free_but_used'].append(b)
            fs.mark(b)

    report['bitmap_errors']['marked_used_but_free'].sort()
    report['bitmap_errors']['marked_free_but_used'].sort()

    # --- Save outputs ---
    fs.save('/app/fs_repaired.img')
    with open('/app/fsck_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f'Replayed {nr} log entries')
    print(f'Orphaned inodes: {report["orphaned_inodes"]}')
    print(f'Bitmap used-but-free: '
          f'{report["bitmap_errors"]["marked_used_but_free"]}')
    print(f'Bitmap free-but-used: '
          f'{report["bitmap_errors"]["marked_free_but_used"]}')
    print(f'Size errors: {report["size_errors"]}')
    print(f'Recovered files: {list(report["recovered_files"].keys())}')


if __name__ == '__main__':
    main()
