"""Verify FAT32 multi-layer forensic repair correctness.

Tests structural integrity, FAT consistency, orphaned cluster detection,
FSInfo accuracy, subdirectory file recovery, data region preservation,
and fsck cleanliness.
"""


import os
import struct
import subprocess
import pytest

REPAIRED_IMG = '/app/repaired.img'
ORIGINAL_IMG = '/app/disk.img'
EXPECTED_DIR = '/expected'


def parse_bpb(img_data):
    """Parse FAT32 BPB fields from boot sector."""
    bps = struct.unpack_from('<H', img_data, 0x0B)[0]
    spc = img_data[0x0D]
    rsvd = struct.unpack_from('<H', img_data, 0x0E)[0]
    nfats = img_data[0x10]
    fatsz = struct.unpack_from('<I', img_data, 0x24)[0]
    rootclus = struct.unpack_from('<I', img_data, 0x2C)[0]
    bkboot = struct.unpack_from('<H', img_data, 0x32)[0]
    fat1 = rsvd * bps
    fat2 = fat1 + fatsz * bps
    fatbytes = fatsz * bps
    data = fat2 + fatsz * bps
    total_sectors = len(img_data) // bps
    data_start_sector = rsvd + nfats * fatsz
    data_sectors = total_sectors - data_start_sector
    max_cluster = 1 + data_sectors // spc
    return {
        'bps': bps, 'spc': spc, 'rsvd': rsvd, 'nfats': nfats,
        'fatsz': fatsz, 'rootclus': rootclus, 'bkboot': bkboot,
        'fat1': fat1, 'fat2': fat2, 'fatbytes': fatbytes,
        'data': data, 'clussz': bps * spc, 'max_cluster': max_cluster
    }


def fat_entry_at(img, fat_start, cluster):
    return struct.unpack_from('<I', img, fat_start + cluster * 4)[0] & 0x0FFFFFFF


def get_chain(img, fat_start, start_cluster):
    chain = []
    c = start_cluster
    visited = set()
    while 2 <= c < 0x0FFFFFF8:
        if c in visited:
            break
        visited.add(c)
        chain.append(c)
        c = fat_entry_at(img, fat_start, c)
    return chain


def cluster_offset(p, cluster):
    return p['data'] + (cluster - 2) * p['clussz']


def parse_dir_name(img, off):
    fname = img[off:off + 8].decode('ascii', errors='replace').rstrip()
    ext = img[off + 8:off + 11].decode('ascii', errors='replace').rstrip()
    return '{}.{}'.format(fname, ext) if ext else fname


def find_dir_entries(img, p, dir_cluster, fat_start):
    entries = []
    cluster = dir_cluster
    while 2 <= cluster < 0x0FFFFFF8:
        base = cluster_offset(p, cluster)
        for i in range(0, p['clussz'], 32):
            off = base + i
            if off + 32 > len(img):
                break
            if img[off] == 0x00:
                return entries
            if img[off] == 0xE5:
                continue
            attr = img[off + 11]
            if (attr & 0x0F) == 0x0F:
                continue
            if attr & 0x08:
                continue
            name = parse_dir_name(img, off)
            hi = struct.unpack_from('<H', img, off + 20)[0]
            lo = struct.unpack_from('<H', img, off + 26)[0]
            first = (hi << 16) | lo
            size = struct.unpack_from('<I', img, off + 28)[0]
            is_dir = bool(attr & 0x10)
            entries.append({
                'name': name, 'cluster': first, 'size': size, 'is_dir': is_dir
            })
        cluster = fat_entry_at(img, fat_start, cluster)
    return entries


def collect_referenced_clusters(img, p, fat_start, dir_cluster):
    """Walk directory tree and collect all clusters referenced by files/dirs."""
    referenced = set()
    dir_chain = get_chain(img, fat_start, dir_cluster)
    referenced.update(dir_chain)

    entries = find_dir_entries(img, p, dir_cluster, fat_start)
    for entry in entries:
        if entry['cluster'] < 2:
            continue
        name = entry['name']
        if entry['is_dir'] and name in ('.', '..'):
            continue
        chain = get_chain(img, fat_start, entry['cluster'])
        referenced.update(chain)
        if entry['is_dir']:
            sub_ref = collect_referenced_clusters(
                img, p, fat_start, entry['cluster'])
            referenced.update(sub_ref)
    return referenced


# ---- Corruption sanity check ----

class TestCorruptionExists:
    def test_original_has_corruption(self):
        """The original disk.img should fail fsck, confirming corruption."""
        result = subprocess.run(
            ['fsck.vfat', '-n', ORIGINAL_IMG],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode != 0, \
            "Original image appears clean - corruption may not have been applied"


# ---- Basic existence checks ----

class TestRepairedImageExists:
    def test_repaired_image_exists(self):
        assert os.path.exists(REPAIRED_IMG), \
            "Repaired image not found at /app/repaired.img"

    def test_repaired_image_not_empty(self):
        size = os.path.getsize(REPAIRED_IMG)
        assert size > 0, "Repaired image is empty"

    def test_repaired_image_same_size(self):
        orig_size = os.path.getsize(ORIGINAL_IMG)
        rep_size = os.path.getsize(REPAIRED_IMG)
        assert orig_size == rep_size, \
            "Image sizes differ: original={}, repaired={}".format(orig_size, rep_size)


# ---- Boot sector checks ----

class TestBootSector:
    @pytest.fixture(autouse=True)
    def setup(self):
        with open(REPAIRED_IMG, 'rb') as f:
            self.img = bytearray(f.read())
        with open(ORIGINAL_IMG, 'rb') as f:
            self.orig = bytearray(f.read())
        self.p = parse_bpb(self.img)

    def test_boot_sector_preserved(self):
        """Boot sector (sector 0) should not be modified."""
        bps = self.p['bps']
        assert self.img[:bps] == self.orig[:bps], \
            "Boot sector was incorrectly modified"

    def test_backup_boot_sector_restored(self):
        """Backup boot sector must match primary boot sector."""
        bps = self.p['bps']
        bk = self.p['bkboot']
        primary = bytes(self.img[:bps])
        backup = bytes(self.img[bk * bps:(bk + 1) * bps])
        assert primary == backup, \
            "Backup boot sector does not match primary"

    def test_backup_fsinfo_has_valid_signature(self):
        """Backup FSInfo sector must have valid lead signature."""
        bps = self.p['bps']
        bk = self.p['bkboot']
        sig = struct.unpack_from('<I', self.img, (bk + 1) * bps)[0]
        assert sig == 0x41615252, \
            "Backup FSInfo lead signature wrong: {:#x}".format(sig)


# ---- FAT consistency checks ----

class TestFATConsistency:
    @pytest.fixture(autouse=True)
    def setup(self):
        with open(REPAIRED_IMG, 'rb') as f:
            self.img = bytearray(f.read())
        self.p = parse_bpb(self.img)

    def test_fat1_equals_fat2(self):
        """FAT1 and FAT2 must be identical after repair."""
        p = self.p
        fat1 = bytes(self.img[p['fat1']:p['fat1'] + p['fatbytes']])
        fat2 = bytes(self.img[p['fat2']:p['fat2'] + p['fatbytes']])
        assert fat1 == fat2, "FAT1 and FAT2 are not identical"

    def test_no_fat_chain_cycles(self):
        """No cluster chain may contain a cycle."""
        p = self.p
        total_entries = p['fatbytes'] // 4
        verified = set()
        for start in range(2, total_entries):
            if start in verified:
                continue
            entry = fat_entry_at(self.img, p['fat1'], start)
            if entry == 0 or entry >= 0x0FFFFFF8:
                verified.add(start)
                continue
            chain = set()
            c = start
            while True:
                if c in chain:
                    pytest.fail(
                        "Cycle detected in FAT chain involving cluster {}".format(c))
                chain.add(c)
                nxt = fat_entry_at(self.img, p['fat1'], c)
                if nxt == 0 or nxt >= 0x0FFFFFF8 or nxt < 2:
                    break
                c = nxt
            verified.update(chain)

    def test_no_cross_linked_clusters(self):
        """No cluster may be referenced by more than one chain."""
        p = self.p
        total_entries = p['fatbytes'] // 4
        referenced_by = {}
        for c in range(2, total_entries):
            entry = fat_entry_at(self.img, p['fat1'], c)
            if entry < 2 or entry >= 0x0FFFFFF8:
                continue
            if entry in referenced_by:
                pytest.fail(
                    "Cluster {} cross-linked: by {} and {}".format(
                        entry, referenced_by[entry], c))
            referenced_by[entry] = c


# ---- Orphaned cluster detection ----

class TestNoOrphanedClusters:
    @pytest.fixture(autouse=True)
    def setup(self):
        with open(REPAIRED_IMG, 'rb') as f:
            self.img = bytearray(f.read())
        self.p = parse_bpb(self.img)

    def test_no_orphaned_clusters(self):
        """All non-zero FAT entries must be referenced by the directory tree."""
        p = self.p
        referenced = collect_referenced_clusters(
            self.img, p, p['fat1'], p['rootclus'])

        orphans = []
        for c in range(2, p['max_cluster'] + 1):
            e = fat_entry_at(self.img, p['fat1'], c)
            if e != 0 and c not in referenced:
                orphans.append(c)

        assert len(orphans) == 0, \
            "Found {} orphaned clusters (unreferenced but allocated): {}".format(
                len(orphans), orphans[:20])


# ---- FSInfo checks ----

class TestFSInfo:
    @pytest.fixture(autouse=True)
    def setup(self):
        with open(REPAIRED_IMG, 'rb') as f:
            self.img = bytearray(f.read())
        self.p = parse_bpb(self.img)

    def test_fsinfo_signatures(self):
        """FSInfo must have correct lead and struct signatures."""
        bps = self.p['bps']
        lead = struct.unpack_from('<I', self.img, bps)[0]
        struc = struct.unpack_from('<I', self.img, bps + 0x1E4)[0]
        assert lead == 0x41615252, \
            "FSInfo lead sig: {:#x}".format(lead)
        assert struc == 0x61417272, \
            "FSInfo struct sig: {:#x}".format(struc)

    def test_fsinfo_free_count(self):
        """FSInfo free cluster count must match actual free clusters."""
        p = self.p
        fsinfo_off = 1 * p['bps']
        reported = struct.unpack_from('<I', self.img, fsinfo_off + 0x1E8)[0]
        actual_free = 0
        for c in range(2, p['max_cluster'] + 1):
            entry = fat_entry_at(self.img, p['fat1'], c)
            if entry == 0:
                actual_free += 1
        assert reported == actual_free, \
            "FSInfo free_count={} but actual={}".format(reported, actual_free)

    def test_fsinfo_next_free(self):
        """FSInfo next_free must point to an actually free cluster."""
        p = self.p
        fsinfo_off = 1 * p['bps']
        next_free = struct.unpack_from('<I', self.img, fsinfo_off + 0x1EC)[0]
        if next_free == 0xFFFFFFFF:
            return  # "unknown" is acceptable
        assert 2 <= next_free <= p['max_cluster'], \
            "next_free={} is outside valid cluster range 2-{}".format(
                next_free, p['max_cluster'])
        entry = fat_entry_at(self.img, p['fat1'], next_free)
        assert entry == 0, \
            "FSInfo next_free={} but cluster is not free (entry={:#x})".format(
                next_free, entry)


# ---- File content recovery checks (including subdirectories) ----

class TestFileRecovery:
    """Verify all six files are extractable with correct content."""

    def _extract_file(self, img_path, fat_path):
        """Extract a file from a FAT image using mtools mcopy."""
        tmp_path = '/tmp/test_extract_{}'.format(
            fat_path.replace('/', '_').replace('.', '_'))
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        try:
            env = os.environ.copy()
            env['MTOOLS_SKIP_CHECK'] = '1'
            result = subprocess.run(
                ['mcopy', '-i', img_path, '::{}'.format(fat_path), tmp_path],
                capture_output=True, text=True, timeout=30, env=env
            )
            if result.returncode != 0:
                return None
            with open(tmp_path, 'rb') as f:
                return f.read()
        except Exception:
            return None
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _read_expected(self, *parts):
        path = os.path.join(EXPECTED_DIR, *parts)
        with open(path, 'rb') as f:
            return f.read()

    # Root-level files
    def test_readme_txt(self):
        content = self._extract_file(REPAIRED_IMG, 'readme.txt')
        assert content is not None, "Failed to extract readme.txt"
        expected = self._read_expected('readme.txt')
        assert content == expected, \
            "readme.txt mismatch: got {} bytes, expected {}".format(
                len(content), len(expected))

    def test_data_bin(self):
        content = self._extract_file(REPAIRED_IMG, 'data.bin')
        assert content is not None, "Failed to extract data.bin"
        expected = self._read_expected('data.bin')
        assert content == expected, "data.bin content mismatch"

    def test_config_ini(self):
        content = self._extract_file(REPAIRED_IMG, 'config.ini')
        assert content is not None, "Failed to extract config.ini"
        expected = self._read_expected('config.ini')
        assert content == expected, "config.ini content mismatch"

    # Subdirectory files
    def test_docs_notes_txt(self):
        content = self._extract_file(REPAIRED_IMG, 'docs/notes.txt')
        assert content is not None, "Failed to extract docs/notes.txt"
        expected = self._read_expected('docs', 'notes.txt')
        assert content == expected, "docs/notes.txt content mismatch"

    def test_docs_report_csv(self):
        content = self._extract_file(REPAIRED_IMG, 'docs/report.csv')
        assert content is not None, "Failed to extract docs/report.csv"
        expected = self._read_expected('docs', 'report.csv')
        assert content == expected, "docs/report.csv content mismatch"

    def test_logs_access_log(self):
        content = self._extract_file(REPAIRED_IMG, 'logs/access.log')
        assert content is not None, "Failed to extract logs/access.log"
        expected = self._read_expected('logs', 'access.log')
        assert content == expected, "logs/access.log content mismatch"


# ---- Data region preservation (anti-cheat) ----

class TestDataRegionPreserved:
    def test_data_region_identical(self):
        """Data clusters must not be modified - only metadata should change."""
        with open(REPAIRED_IMG, 'rb') as f:
            repaired = f.read()
        with open(ORIGINAL_IMG, 'rb') as f:
            original = f.read()
        p = parse_bpb(bytearray(repaired))
        data_start = p['data']
        assert repaired[data_start:] == original[data_start:], \
            "Data region was modified - only FAT metadata should change"


# ---- Overall filesystem consistency ----

class TestFsck:
    def test_fsck_clean(self):
        """fsck.vfat must report no errors on the repaired image."""
        result = subprocess.run(
            ['fsck.vfat', '-n', REPAIRED_IMG],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, \
            "fsck.vfat found errors (exit {}):\n{}\n{}".format(
                result.returncode, result.stdout, result.stderr)
