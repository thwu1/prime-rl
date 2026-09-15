
"""
Tests for xv6 filesystem consistency checker.
Generates xv6 filesystem images with known corruptions and verifies
that /app/xv6-fsck correctly detects each inconsistency type.
Also verifies the tool is a compiled ELF binary.
"""

import struct
import os
import subprocess
import json
import tempfile
import pytest

# -- xv6 filesystem constants --
BSIZE = 1024
NDIRECT = 12
NINDIRECT = BSIZE // 4  # 256
IPB = BSIZE // 64       # 16
BPB = BSIZE * 8         # 8192
T_DIR = 1
T_FILE = 2
FSMAGIC = 0x10203040
DIRSIZ = 14
ROOTINO = 1


class XV6Image:
    """Programmatically creates xv6 filesystem images for testing."""

    def __init__(self, fssize=1000, ninodes=200):
        self.fssize = fssize
        self.ninodes = ninodes
        self.nlog = 30

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

        # Write superblock at block 1
        struct.pack_into('<IIIIIIII', self.data, BSIZE,
                         FSMAGIC, fssize, self.nblocks, ninodes,
                         self.nlog, self.logstart, self.inodestart, self.bmapstart)

        # Mark all metadata blocks in bitmap
        for b in range(self.datastart):
            self._set_bitmap(b)

        # Create root directory with "." and ".." entries
        root_block = self._alloc_block()
        dot = self._make_dirent(ROOTINO, '.')
        dotdot = self._make_dirent(ROOTINO, '..')
        self._write_at(root_block * BSIZE, dot + dotdot)

        addrs = [0] * 13
        addrs[0] = root_block
        # root nlink = 1 (from its own ".." entry pointing to itself)
        self._write_inode(ROOTINO, T_DIR, 0, 0, 1, 32, addrs)

    # -- Low-level helpers --

    def _set_bitmap(self, block):
        bit = block % BPB
        bmap_block_idx = block // BPB
        byte_offset = (self.bmapstart + bmap_block_idx) * BSIZE + bit // 8
        self.data[byte_offset] |= (1 << (bit % 8))

    def _clear_bitmap(self, block):
        bit = block % BPB
        bmap_block_idx = block // BPB
        byte_offset = (self.bmapstart + bmap_block_idx) * BSIZE + bit // 8
        self.data[byte_offset] &= ~(1 << (bit % 8))

    def _write_at(self, offset, payload):
        self.data[offset:offset + len(payload)] = payload

    def _make_dirent(self, inum, name):
        name_bytes = name.encode('ascii')[:DIRSIZ]
        name_bytes = name_bytes.ljust(DIRSIZ, b'\x00')
        return struct.pack('<H', inum) + name_bytes

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
        addrs = [struct.unpack_from('<I', self.data, pos + 12 + i * 4)[0] for i in range(13)]
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
        if block_idx >= NDIRECT:
            raise RuntimeError("directory too large for test helper")
        if addrs[block_idx] == 0:
            addrs[block_idx] = self._alloc_block()
        pos = addrs[block_idx] * BSIZE + offset_in_block
        self.data[pos:pos + 16] = entry
        sz += 16
        self._write_inode(parent_inum, t, maj, mi, nl, sz, addrs)

    # -- High-level builders --

    def add_file(self, name, content_size, parent_inum=ROOTINO):
        """Add a regular file. Returns (inum, list_of_all_block_numbers)."""
        inum = self._alloc_inode()
        addrs = [0] * 13
        all_blocks = []
        remaining = content_size
        block_idx = 0

        # Direct blocks
        while remaining > 0 and block_idx < NDIRECT:
            b = self._alloc_block()
            chunk_len = min(remaining, BSIZE)
            filler = bytes([(inum + block_idx + i) & 0xFF for i in range(chunk_len)])
            self._write_at(b * BSIZE, filler)
            addrs[block_idx] = b
            all_blocks.append(b)
            remaining -= BSIZE
            block_idx += 1

        # Indirect blocks
        if remaining > 0:
            indirect_b = self._alloc_block()
            addrs[NDIRECT] = indirect_b
            all_blocks.append(indirect_b)
            j = 0
            while remaining > 0 and j < NINDIRECT:
                b = self._alloc_block()
                chunk_len = min(remaining, BSIZE)
                filler = bytes([(inum + NDIRECT + j + i) & 0xFF for i in range(chunk_len)])
                self._write_at(b * BSIZE, filler)
                struct.pack_into('<I', self.data, indirect_b * BSIZE + j * 4, b)
                all_blocks.append(b)
                remaining -= BSIZE
                j += 1

        self._write_inode(inum, T_FILE, 0, 0, 1, content_size, addrs)
        self._add_dir_entry(parent_inum, name, inum)
        return inum, all_blocks

    def add_dir(self, name, parent_inum=ROOTINO):
        """Add a subdirectory. Returns inum."""
        inum = self._alloc_inode()
        dir_block = self._alloc_block()
        dot = self._make_dirent(inum, '.')
        dotdot = self._make_dirent(parent_inum, '..')
        self._write_at(dir_block * BSIZE, dot + dotdot)

        addrs = [0] * 13
        addrs[0] = dir_block
        self._write_inode(inum, T_DIR, 0, 0, 1, 32, addrs)

        self._add_dir_entry(parent_inum, name, inum)

        # Increment parent nlink for the ".." reference
        t, maj, mi, nl, sz, a = self._read_inode_raw(parent_inum)
        self._write_inode(parent_inum, t, maj, mi, nl + 1, sz, a)
        return inum

    # -- Corruption methods --

    def corrupt_clear_bitmap(self, block):
        self._clear_bitmap(block)

    def corrupt_set_bitmap(self, block):
        self._set_bitmap(block)

    def corrupt_set_nlink(self, inum, nlink):
        t, maj, mi, _, sz, addrs = self._read_inode_raw(inum)
        self._write_inode(inum, t, maj, mi, nlink, sz, addrs)

    def corrupt_add_orphan_inode(self, content_size=100):
        """Create an allocated inode with data but no directory entry."""
        inum = self._alloc_inode()
        addrs = [0] * 13
        b = self._alloc_block()
        self._write_at(b * BSIZE, bytes([0xAA] * min(content_size, BSIZE)))
        addrs[0] = b
        self._write_inode(inum, T_FILE, 0, 0, 1, content_size, addrs)
        return inum

    def corrupt_duplicate_block(self, src_inum, block, dest_name='dupfile', parent=ROOTINO):
        """Create a file whose first data block duplicates another inode's block."""
        inum = self._alloc_inode()
        addrs = [0] * 13
        addrs[0] = block
        self._write_inode(inum, T_FILE, 0, 0, 1, BSIZE, addrs)
        self._add_dir_entry(parent, dest_name, inum)
        return inum

    def corrupt_add_file_with_bad_ref(self, name, bad_block, parent=ROOTINO):
        """Create a file with one valid block and one invalid block reference."""
        inum = self._alloc_inode()
        addrs = [0] * 13
        b = self._alloc_block()
        self._write_at(b * BSIZE, bytes([0x42] * BSIZE))
        addrs[0] = b
        addrs[1] = bad_block  # Invalid reference (not allocated via _alloc_block)
        self._write_inode(inum, T_FILE, 0, 0, 1, BSIZE * 2, addrs)
        self._add_dir_entry(parent, name, inum)
        return inum

    def save(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(self.data)


# -- Test helpers --

def run_fsck(image_path):
    """Run the fsck tool and return parsed JSON result."""
    result = subprocess.run(
        ['/app/xv6-fsck', image_path],
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, (
        f"xv6-fsck exited with code {result.returncode}.\n"
        f"stdout: {result.stdout[:2000]}\nstderr: {result.stderr[:2000]}"
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail(f"xv6-fsck output is not valid JSON:\n{result.stdout[:2000]}")


def errors_of_type(report, error_type):
    """Filter errors by type."""
    return [e for e in report['errors'] if e['type'] == error_type]


@pytest.fixture
def tmpdir():
    with tempfile.TemporaryDirectory() as d:
        yield d


# -- Tests --

class TestBinaryRequirements:
    def test_is_compiled_elf(self):
        """xv6-fsck must be a compiled ELF binary, not a script."""
        assert os.path.isfile('/app/xv6-fsck'), "/app/xv6-fsck does not exist"
        with open('/app/xv6-fsck', 'rb') as f:
            magic = f.read(4)
        assert magic == b'\x7fELF', (
            "xv6-fsck must be a compiled ELF binary, not a script "
            f"(got magic bytes: {magic.hex()})"
        )

    def test_is_executable(self):
        """xv6-fsck must have executable permissions."""
        assert os.access('/app/xv6-fsck', os.X_OK), (
            "/app/xv6-fsck is not executable"
        )

    def test_reference_image_clean(self):
        """The provided reference.img should produce zero errors."""
        assert os.path.isfile('/app/reference.img'), "/app/reference.img not found"
        report = run_fsck('/app/reference.img')
        assert 'errors' in report
        assert len(report['errors']) == 0, (
            f"Reference image should have no errors, got: {report['errors']}"
        )


class TestCleanImage:
    def test_no_errors_simple(self, tmpdir):
        """A valid image with files and a subdirectory should have zero errors."""
        img = XV6Image()
        img.add_file("hello", 500)
        img.add_file("world", 2000)
        img.add_dir("subdir")
        path = os.path.join(tmpdir, "clean.img")
        img.save(path)
        report = run_fsck(path)
        assert 'errors' in report
        assert len(report['errors']) == 0, f"Expected no errors, got: {report['errors']}"

    def test_no_errors_with_indirect(self, tmpdir):
        """A file spanning direct + indirect blocks should be consistent."""
        img = XV6Image()
        img.add_file("bigfile", 15 * BSIZE)  # 12 direct + 3 via indirect
        path = os.path.join(tmpdir, "clean_indirect.img")
        img.save(path)
        report = run_fsck(path)
        assert len(report['errors']) == 0, f"Expected no errors, got: {report['errors']}"


class TestBitmapErrors:
    def test_bitmap_marked_free(self, tmpdir):
        """Block referenced by inode but bitmap bit cleared."""
        img = XV6Image()
        inum, blocks = img.add_file("hello", 500)
        target_block = blocks[0]
        img.corrupt_clear_bitmap(target_block)
        path = os.path.join(tmpdir, "bitmap_free.img")
        img.save(path)

        report = run_fsck(path)
        errs = errors_of_type(report, 'BITMAP_MARKED_FREE')
        assert len(errs) == 1, f"Expected 1 BITMAP_MARKED_FREE, got {len(errs)}: {errs}"
        assert errs[0]['block'] == target_block
        assert inum in errs[0]['inodes']

    def test_bitmap_marked_used(self, tmpdir):
        """Unreferenced data block with bitmap bit set."""
        img = XV6Image()
        img.add_file("hello", 500)
        unused_block = img.fssize - 1
        img.corrupt_set_bitmap(unused_block)
        path = os.path.join(tmpdir, "bitmap_used.img")
        img.save(path)

        report = run_fsck(path)
        errs = errors_of_type(report, 'BITMAP_MARKED_USED')
        assert len(errs) == 1, f"Expected 1 BITMAP_MARKED_USED, got {len(errs)}: {errs}"
        assert errs[0]['block'] == unused_block


class TestNlinkErrors:
    def test_nlink_too_high(self, tmpdir):
        """File nlink set higher than actual directory reference count."""
        img = XV6Image()
        inum, _ = img.add_file("hello", 500)
        img.corrupt_set_nlink(inum, 5)
        path = os.path.join(tmpdir, "nlink_high.img")
        img.save(path)

        report = run_fsck(path)
        errs = errors_of_type(report, 'INODE_NLINK_MISMATCH')
        matching = [e for e in errs if e['inode'] == inum]
        assert len(matching) == 1, f"Expected INODE_NLINK_MISMATCH for inode {inum}, got: {errs}"
        assert matching[0]['expected'] == 1
        assert matching[0]['actual'] == 5

    def test_nlink_too_low(self, tmpdir):
        """File nlink set lower than actual directory reference count."""
        img = XV6Image()
        inum, _ = img.add_file("hello", 500)
        img.corrupt_set_nlink(inum, 0)
        path = os.path.join(tmpdir, "nlink_low.img")
        img.save(path)

        report = run_fsck(path)
        errs = errors_of_type(report, 'INODE_NLINK_MISMATCH')
        matching = [e for e in errs if e['inode'] == inum]
        assert len(matching) == 1
        assert matching[0]['expected'] == 1
        assert matching[0]['actual'] == 0

    def test_directory_nlink_mismatch(self, tmpdir):
        """Directory nlink wrong after adding subdirectories."""
        img = XV6Image()
        img.add_dir("sub1")
        img.add_dir("sub2")
        # Root should have nlink=3 (own ".." + two subdirs' "..")
        # Corrupt it to 1
        img.corrupt_set_nlink(ROOTINO, 1)
        path = os.path.join(tmpdir, "dir_nlink.img")
        img.save(path)

        report = run_fsck(path)
        errs = errors_of_type(report, 'INODE_NLINK_MISMATCH')
        matching = [e for e in errs if e['inode'] == ROOTINO]
        assert len(matching) == 1
        assert matching[0]['expected'] == 3
        assert matching[0]['actual'] == 1


class TestOrphanInode:
    def test_orphan_file(self, tmpdir):
        """Allocated inode with no directory entry pointing to it."""
        img = XV6Image()
        img.add_file("legit", 500)
        orphan_inum = img.corrupt_add_orphan_inode(100)
        path = os.path.join(tmpdir, "orphan.img")
        img.save(path)

        report = run_fsck(path)
        orphan_errs = errors_of_type(report, 'ORPHAN_INODE')
        assert len(orphan_errs) == 1
        assert orphan_errs[0]['inode'] == orphan_inum

        # Orphan should also have nlink mismatch (actual=1, expected=0)
        nlink_errs = errors_of_type(report, 'INODE_NLINK_MISMATCH')
        matching = [e for e in nlink_errs if e['inode'] == orphan_inum]
        assert len(matching) == 1
        assert matching[0]['expected'] == 0
        assert matching[0]['actual'] == 1


class TestDuplicateBlock:
    def test_two_inodes_share_block(self, tmpdir):
        """Two different inodes reference the same data block."""
        img = XV6Image()
        inum1, blocks1 = img.add_file("file1", 500)
        shared_block = blocks1[0]
        inum2 = img.corrupt_duplicate_block(inum1, shared_block, "file2")
        path = os.path.join(tmpdir, "dupblock.img")
        img.save(path)

        report = run_fsck(path)
        errs = errors_of_type(report, 'DUPLICATE_BLOCK_REF')
        assert len(errs) == 1, f"Expected 1 DUPLICATE_BLOCK_REF, got {len(errs)}: {errs}"
        assert errs[0]['block'] == shared_block
        assert sorted(errs[0]['inodes']) == sorted([inum1, inum2])


class TestInvalidBlockRef:
    def test_block_out_of_range(self, tmpdir):
        """Block reference exceeds filesystem size."""
        img = XV6Image()
        bad_block = img.fssize + 100
        inum = img.corrupt_add_file_with_bad_ref("badfile", bad_block)
        path = os.path.join(tmpdir, "badref_oor.img")
        img.save(path)

        report = run_fsck(path)
        errs = errors_of_type(report, 'INVALID_BLOCK_REF')
        assert len(errs) == 1
        assert errs[0]['inode'] == inum
        assert errs[0]['block'] == bad_block

    def test_block_in_metadata_region(self, tmpdir):
        """Block reference points to metadata area (superblock)."""
        img = XV6Image()
        meta_block = 1  # superblock
        inum = img.corrupt_add_file_with_bad_ref("badfile", meta_block)
        path = os.path.join(tmpdir, "badref_meta.img")
        img.save(path)

        report = run_fsck(path)
        errs = errors_of_type(report, 'INVALID_BLOCK_REF')
        assert len(errs) == 1
        assert errs[0]['inode'] == inum
        assert errs[0]['block'] == meta_block

    def test_indirect_block_corruption(self, tmpdir):
        """An entry inside an indirect block points out of range."""
        img = XV6Image()
        inum, blocks = img.add_file("bigfile", 15 * BSIZE)
        # blocks: [b0..b11, indirect_b, ib0, ib1, ib2]
        indirect_b = blocks[12]
        original_ib0 = blocks[13]
        bad_block = img.fssize + 999

        # Overwrite first entry in indirect block with bad reference
        struct.pack_into('<I', img.data, indirect_b * BSIZE, bad_block)
        # Clear bitmap for original block to avoid stale BITMAP_MARKED_USED
        img.corrupt_clear_bitmap(original_ib0)

        path = os.path.join(tmpdir, "badref_indirect.img")
        img.save(path)

        report = run_fsck(path)
        errs = errors_of_type(report, 'INVALID_BLOCK_REF')
        assert len(errs) == 1, f"Expected 1 INVALID_BLOCK_REF, got {len(errs)}: {errs}"
        assert errs[0]['inode'] == inum
        assert errs[0]['block'] == bad_block


class TestCombined:
    def test_multiple_corruption_types(self, tmpdir):
        """Multiple corruption types present simultaneously."""
        img = XV6Image()
        inum1, blocks1 = img.add_file("file1", 500)
        inum2, blocks2 = img.add_file("file2", 1000)
        img.add_dir("mydir")

        # Corruption 1: bitmap marked free for file1's block
        img.corrupt_clear_bitmap(blocks1[0])

        # Corruption 2: bitmap marked used for an unreferenced block
        unused_block = img.fssize - 2
        img.corrupt_set_bitmap(unused_block)

        # Corruption 3: wrong nlink for file2
        img.corrupt_set_nlink(inum2, 3)

        # Corruption 4: orphan inode
        orphan = img.corrupt_add_orphan_inode(200)

        path = os.path.join(tmpdir, "combined.img")
        img.save(path)

        report = run_fsck(path)

        bitmap_free = errors_of_type(report, 'BITMAP_MARKED_FREE')
        bitmap_used = errors_of_type(report, 'BITMAP_MARKED_USED')
        nlink = errors_of_type(report, 'INODE_NLINK_MISMATCH')
        orphans = errors_of_type(report, 'ORPHAN_INODE')

        assert len(bitmap_free) == 1
        assert bitmap_free[0]['block'] == blocks1[0]

        assert len(bitmap_used) == 1
        assert bitmap_used[0]['block'] == unused_block

        # nlink mismatches: file2 (expected=1, actual=3) + orphan (expected=0, actual=1)
        assert len(nlink) == 2
        file2_nlink = [e for e in nlink if e['inode'] == inum2]
        assert len(file2_nlink) == 1
        assert file2_nlink[0]['expected'] == 1
        assert file2_nlink[0]['actual'] == 3
        orphan_nlink = [e for e in nlink if e['inode'] == orphan]
        assert len(orphan_nlink) == 1

        assert len(orphans) == 1
        assert orphans[0]['inode'] == orphan
