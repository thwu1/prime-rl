
"""Verification tests for xv6 fsck task.

Tests validate both the JSON report and the repaired disk image
against known ground-truth corruption parameters.
"""

import json
import struct
import os
import pytest

# xv6 constants
BSIZE = 1024
FSMAGIC = 0x10203040
NDIRECT = 12
T_DIR = 1
T_FILE = 2
DIRSIZ = 14
IPB = BSIZE // 64
BPB = BSIZE * 8


# ---- helpers for reading the repaired image ----

def read_superblock(data):
    off = BSIZE
    vals = struct.unpack_from('<IIIIIIII', data, off)
    return {
        'magic': vals[0], 'size': vals[1], 'nblocks': vals[2],
        'ninodes': vals[3], 'nlog': vals[4], 'logstart': vals[5],
        'inodestart': vals[6], 'bmapstart': vals[7]
    }


def read_inode(data, inum, sb):
    block = inum // IPB + sb['inodestart']
    off = block * BSIZE + (inum % IPB) * 64
    t, maj, mi, nl, sz = struct.unpack_from('<hhhhI', data, off)
    addrs = [struct.unpack_from('<I', data, off + 12 + i * 4)[0]
             for i in range(NDIRECT + 1)]
    return {'type': t, 'major': maj, 'minor': mi,
            'nlink': nl, 'size': sz, 'addrs': addrs}


def read_log_header(data, sb):
    off = sb['logstart'] * BSIZE
    n = struct.unpack_from('<i', data, off)[0]
    blocks = [struct.unpack_from('<i', data, off + 4 + i * 4)[0]
              for i in range(max(n, 0))]
    return n, blocks


def is_block_marked(data, blockno, sb):
    base = (blockno // BPB + sb['bmapstart']) * BSIZE
    byte_idx = (blockno % BPB) // 8
    bit = 1 << (blockno % 8)
    return bool(data[base + byte_idx] & bit)


def read_dirents(data, block_no, size):
    entries = []
    off = block_no * BSIZE
    num = min(size, BSIZE) // 16
    for i in range(num):
        inum = struct.unpack_from('<H', data, off + i * 16)[0]
        raw = data[off + i * 16 + 2: off + i * 16 + 16]
        name = raw.split(b'\x00')[0].decode('ascii', errors='replace')
        if inum != 0:
            entries.append((inum, name))
    return entries


# ---- fixtures ----

@pytest.fixture(scope='module')
def report():
    path = '/app/fsck_report.json'
    assert os.path.exists(path), 'fsck_report.json not found'
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope='module')
def img_data():
    path = '/app/fs_repaired.img'
    assert os.path.exists(path), 'fs_repaired.img not found'
    with open(path, 'rb') as f:
        return f.read()


@pytest.fixture(scope='module')
def sb(img_data):
    return read_superblock(img_data)


# ================ Report tests ================

class TestReport:
    def test_log_entries_replayed(self, report):
        assert report['log_entries_replayed'] == 2

    def test_orphaned_inodes(self, report):
        orphans = sorted(report['orphaned_inodes'])
        assert orphans == [10, 11]

    def test_bitmap_leaked_block(self, report):
        used_but_free = report['bitmap_errors']['marked_used_but_free']
        assert 300 in used_but_free

    def test_bitmap_missing_block(self, report):
        free_but_used = report['bitmap_errors']['marked_free_but_used']
        assert 51 in free_but_used

    def test_size_error_inode6(self, report):
        found = False
        for err in report['size_errors']:
            if err['inum'] == 6:
                assert err['reported_size'] == 5000
                assert err['correct_size'] == 3072
                found = True
        assert found, 'Size error for inode 6 not reported'

    def test_recovered_file_content(self, report):
        recovered = report.get('recovered_files', {})
        assert 'recovered.txt' in recovered
        assert recovered['recovered.txt'] == 'Log recovery successful!\n'


# ================ Repaired image tests ================

class TestRepairedImage:
    def test_superblock_valid(self, img_data, sb):
        assert sb['magic'] == FSMAGIC

    def test_log_cleared(self, img_data, sb):
        n, _ = read_log_header(img_data, sb)
        assert n == 0, 'Log should be cleared after replay'

    def test_inode7_created(self, img_data, sb):
        i7 = read_inode(img_data, 7, sb)
        assert i7['type'] == T_FILE
        assert i7['nlink'] == 1
        assert i7['size'] == 25

    def test_recovered_txt_in_root(self, img_data, sb):
        root = read_inode(img_data, 1, sb)
        entries = read_dirents(img_data, root['addrs'][0], root['size'])
        found = False
        for inum, name in entries:
            if name == 'recovered.txt':
                assert inum == 7
                found = True
        assert found, 'recovered.txt not found in root directory'

    def test_orphan_inodes_freed(self, img_data, sb):
        i10 = read_inode(img_data, 10, sb)
        i11 = read_inode(img_data, 11, sb)
        assert i10['type'] == 0, 'Orphaned inode 10 not freed'
        assert i11['type'] == 0, 'Orphaned inode 11 not freed'

    def test_orphan_blocks_freed(self, img_data, sb):
        assert not is_block_marked(img_data, 60, sb), \
            'Block 60 (orphan 10 data) should be freed'
        assert not is_block_marked(img_data, 61, sb), \
            'Block 61 (orphan 11 data) should be freed'

    def test_leaked_block_freed(self, img_data, sb):
        assert not is_block_marked(img_data, 300, sb), \
            'Leaked block 300 should be freed in bitmap'

    def test_missing_block_marked(self, img_data, sb):
        assert is_block_marked(img_data, 51, sb), \
            'Referenced block 51 should be marked in bitmap'

    def test_inode6_size_corrected(self, img_data, sb):
        i6 = read_inode(img_data, 6, sb)
        assert i6['size'] == 3072, \
            f'Inode 6 size should be 3072, got {i6["size"]}'

    def test_hello_txt_preserved(self, img_data, sb):
        i2 = read_inode(img_data, 2, sb)
        assert i2['type'] == T_FILE
        assert i2['size'] == 18
        off = i2['addrs'][0] * BSIZE
        assert img_data[off:off + 18] == b'Hello, xv6 world!\n'

    def test_subdir_preserved(self, img_data, sb):
        i4 = read_inode(img_data, 4, sb)
        assert i4['type'] == T_DIR

    def test_readme_preserved(self, img_data, sb):
        i5 = read_inode(img_data, 5, sb)
        assert i5['type'] == T_FILE
        assert i5['size'] == 18
        off = i5['addrs'][0] * BSIZE
        assert img_data[off:off + 18] == b'This is a readme.\n'

    def test_databin_preserved(self, img_data, sb):
        i3 = read_inode(img_data, 3, sb)
        assert i3['type'] == T_FILE
        assert i3['size'] == 1500
        off0 = i3['addrs'][0] * BSIZE
        off1 = i3['addrs'][1] * BSIZE
        content = img_data[off0:off0 + BSIZE] + img_data[off1:off1 + 476]
        expected = bytes([i % 256 for i in range(1500)])
        assert content == expected
