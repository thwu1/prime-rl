"""
Tests for the TKV1 Flash Key-Value Store implementation.

Verifies API correctness, on-flash binary format compliance,
crash recovery, crash-safe compaction, wear-leveling, edge cases,
and cross-compatibility with the C reference implementation.
"""

import struct
import zlib
import sys
import os
import subprocess
import tempfile

import pytest

sys.path.insert(0, '/app')

from flash_sim import FlashSimulator

# ---------------------------------------------------------------------------
# Reference implementations — independent of the solution under test
# ---------------------------------------------------------------------------

PAGE_MAGIC = b'\x54\x4b\x56\x31'
ENTRY_MAGIC = b'\xae\x73'
PAGE_HEADER_SIZE = 12
ENTRY_HEADER_SIZE = 16

TICKV_TOOL = '/app/tickv_ref/tickv_tool'


def _ref_fnv1a_32(data: bytes) -> int:
    """Reference FNV-1a 32-bit hash."""
    h = 0x811c9dc5
    for b in data:
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def _ref_compute_crc(key_len: int, value_len: int, key_hash: int,
                     key: bytes, value: bytes) -> int:
    """Reference CRC32 computation (state byte excluded)."""
    crc_data = struct.pack('<BII', key_len, value_len, key_hash) + key + value
    return zlib.crc32(crc_data) & 0xFFFFFFFF


def _make_store(num_pages=4):
    """Helper: create a formatted FlashKVStore."""
    from kvstore import FlashKVStore
    flash = FlashSimulator(num_pages * 4096)
    store = FlashKVStore(flash)
    store.format()
    return flash, store


# ---------------------------------------------------------------------------
# Crash simulation helper
# ---------------------------------------------------------------------------

class CrashableFlash:
    """Wraps FlashSimulator to simulate power loss after N mutating ops."""

    class PowerLoss(Exception):
        pass

    def __init__(self, flash, ops_until_crash):
        self._flash = flash
        self._remaining = ops_until_crash

    @property
    def size(self):
        return self._flash.size

    @property
    def page_size(self):
        return self._flash.page_size

    @property
    def num_pages(self):
        return self._flash.num_pages

    @property
    def erase_counts(self):
        return self._flash.erase_counts

    def read(self, offset, length):
        return self._flash.read(offset, length)

    def write(self, offset, data):
        if self._remaining <= 0:
            raise self.PowerLoss()
        self._remaining -= 1
        self._flash.write(offset, data)

    def erase_page(self, page_num):
        if self._remaining <= 0:
            raise self.PowerLoss()
        self._remaining -= 1
        self._flash.erase_page(page_num)

    def get_raw(self):
        return self._flash.get_raw()

    def load_raw(self, data):
        self._flash.load_raw(data)


class OpCountingFlash:
    """Wraps FlashSimulator to count write/erase operations."""

    def __init__(self, flash):
        self._flash = flash
        self.op_count = 0

    @property
    def size(self):
        return self._flash.size

    @property
    def page_size(self):
        return self._flash.page_size

    @property
    def num_pages(self):
        return self._flash.num_pages

    @property
    def erase_counts(self):
        return self._flash.erase_counts

    def read(self, offset, length):
        return self._flash.read(offset, length)

    def write(self, offset, data):
        self.op_count += 1
        self._flash.write(offset, data)

    def erase_page(self, page_num):
        self.op_count += 1
        self._flash.erase_page(page_num)

    def get_raw(self):
        return self._flash.get_raw()

    def load_raw(self, data):
        self._flash.load_raw(data)


# ===================================================================
# 1. Basic CRUD operations
# ===================================================================

class TestBasicOperations:
    def test_format_empty(self):
        from kvstore import FlashKVStore
        flash, store = _make_store()
        assert store.get(b"missing") is None
        assert store.list_keys() == []

    def test_put_get_single(self):
        flash, store = _make_store()
        assert store.put(b"hello", b"world") is True
        assert store.get(b"hello") == b"world"

    def test_put_get_multiple(self):
        flash, store = _make_store()
        pairs = {b"k1": b"v1", b"k2": b"v2", b"k3": b"v3", b"k4": b"v4"}
        for k, v in pairs.items():
            assert store.put(k, v) is True
        for k, v in pairs.items():
            assert store.get(k) == v

    def test_overwrite(self):
        flash, store = _make_store()
        store.put(b"key", b"old")
        store.put(b"key", b"new")
        assert store.get(b"key") == b"new"

    def test_delete(self):
        flash, store = _make_store()
        store.put(b"key", b"val")
        assert store.delete(b"key") is True
        assert store.get(b"key") is None

    def test_delete_nonexistent(self):
        flash, store = _make_store()
        assert store.delete(b"ghost") is False

    def test_list_keys(self):
        flash, store = _make_store()
        store.put(b"c", b"3")
        store.put(b"a", b"1")
        store.put(b"b", b"2")
        assert sorted(store.list_keys()) == [b"a", b"b", b"c"]

    def test_empty_value(self):
        flash, store = _make_store()
        store.put(b"empty", b"")
        assert store.get(b"empty") == b""

    def test_put_after_delete(self):
        flash, store = _make_store()
        store.put(b"key", b"first")
        store.delete(b"key")
        store.put(b"key", b"second")
        assert store.get(b"key") == b"second"

    def test_multiple_overwrites(self):
        flash, store = _make_store()
        for i in range(20):
            store.put(b"counter", str(i).encode())
        assert store.get(b"counter") == b"19"


# ===================================================================
# 2. Page management
# ===================================================================

class TestPageManagement:
    def test_page_transition(self):
        """Entries spanning multiple pages all readable."""
        flash, store = _make_store(num_pages=4)
        entries = {}
        for i in range(80):
            key = f"key{i:03d}".encode()
            val = b"x" * 80
            assert store.put(key, val) is True
            entries[key] = val
        for k, v in entries.items():
            assert store.get(k) == v

    def test_full_flash(self):
        """PUT returns False when flash is full."""
        flash, store = _make_store(num_pages=2)
        written = 0
        while store.put(f"k{written:05d}".encode(), b"v" * 40):
            written += 1
        assert written > 0
        # All written entries still readable
        for j in range(written):
            assert store.get(f"k{j:05d}".encode()) == b"v" * 40

    def test_large_entry_fits_page(self):
        """Entry that almost fills an entire page."""
        flash, store = _make_store()
        max_val = 4096 - PAGE_HEADER_SIZE - ENTRY_HEADER_SIZE - 3  # key=b"ab"
        store.put(b"ab", b"X" * max_val)  # should NOT raise
        assert store.get(b"ab") == b"X" * max_val

    def test_entry_causes_page_switch(self):
        """An entry that doesn't fit triggers switch to next page."""
        flash, store = _make_store(num_pages=4)
        # Fill page 0 with small entries until little space remains
        i = 0
        while True:
            key = f"s{i:04d}".encode()
            val = b"y" * 50
            entry_size = ENTRY_HEADER_SIZE + len(key) + len(val)
            # Check approximate remaining space on page 0
            used = PAGE_HEADER_SIZE + i * entry_size
            if used + entry_size > 4096:
                break
            store.put(key, val)
            i += 1
        # Now write a big entry that must go to page 1
        big_key = b"BIG"
        big_val = b"Z" * 500
        assert store.put(big_key, big_val) is True
        assert store.get(big_key) == big_val


# ===================================================================
# 3. On-flash format verification
# ===================================================================

class TestFormatVerification:
    def test_page_header_format(self):
        flash, store = _make_store()
        raw = flash.read(0, PAGE_HEADER_SIZE)
        assert raw[0:4] == PAGE_MAGIC
        assert raw[4] == 0x0F  # ACTIVE
        seq = struct.unpack_from('<H', raw, 5)[0]
        assert seq == 0
        assert raw[7] == 0xFF  # reserved
        ec = struct.unpack_from('<I', raw, 8)[0]
        assert ec > 0  # at least 1 erase from format()

    def test_entry_header_format(self):
        flash, store = _make_store()
        store.put(b"test", b"data")
        raw = flash.read(PAGE_HEADER_SIZE, ENTRY_HEADER_SIZE + 4 + 4)
        # Magic
        assert raw[0:2] == ENTRY_MAGIC
        # State = valid
        assert raw[2] == 0x0F
        # Key length
        assert raw[3] == 4
        # Value length
        assert struct.unpack_from('<I', raw, 4)[0] == 4
        # Key hash
        expected_hash = _ref_fnv1a_32(b"test")
        assert struct.unpack_from('<I', raw, 8)[0] == expected_hash
        # CRC
        expected_crc = _ref_compute_crc(4, 4, expected_hash, b"test", b"data")
        assert struct.unpack_from('<I', raw, 12)[0] == expected_crc
        # Key and value bytes
        assert raw[16:20] == b"test"
        assert raw[20:24] == b"data"

    def test_invalidation_preserves_entry(self):
        """Overwriting a key invalidates old entry state byte only."""
        flash, store = _make_store()
        store.put(b"k1", b"v1")
        before = flash.read(PAGE_HEADER_SIZE, ENTRY_HEADER_SIZE + 2 + 2)
        assert before[2] == 0x0F  # valid

        store.put(b"k1", b"v2")
        after = flash.read(PAGE_HEADER_SIZE, ENTRY_HEADER_SIZE + 2 + 2)
        assert after[2] == 0x00  # invalidated
        # Everything else unchanged
        assert after[3:] == before[3:]

    def test_page_marked_full(self):
        """When a page fills up, its status becomes 0x00."""
        flash, store = _make_store(num_pages=4)
        # Fill page 0
        for i in range(200):
            key = f"fill{i:04d}".encode()
            val = b"d" * 60
            if not store.put(key, val):
                break
        status = flash.read(4, 1)[0]
        # Page 0 should be full if we wrote enough entries
        # (entries ~ 84 bytes each, page capacity ~ 4084 => ~48 entries per page)
        if i > 50:
            assert status == 0x00


# ===================================================================
# 4. Crash recovery
# ===================================================================

class TestCrashRecovery:
    def test_recovery_clean(self):
        """Recover from a clean flash image."""
        from kvstore import FlashKVStore
        flash, store = _make_store()
        store.put(b"alpha", b"first")
        store.put(b"beta", b"second")
        store.put(b"gamma", b"third")

        flash2 = FlashSimulator(flash.size)
        flash2.load_raw(flash.get_raw())
        store2 = FlashKVStore(flash2)

        assert store2.get(b"alpha") == b"first"
        assert store2.get(b"beta") == b"second"
        assert store2.get(b"gamma") == b"third"

    def test_recovery_with_overwrites(self):
        """Recovery reflects latest value after overwrites."""
        from kvstore import FlashKVStore
        flash, store = _make_store()
        store.put(b"key", b"old")
        store.put(b"key", b"new")

        flash2 = FlashSimulator(flash.size)
        flash2.load_raw(flash.get_raw())
        store2 = FlashKVStore(flash2)
        assert store2.get(b"key") == b"new"

    def test_recovery_with_deletes(self):
        """Recovery correctly handles deleted keys."""
        from kvstore import FlashKVStore
        flash, store = _make_store()
        store.put(b"keep", b"yes")
        store.put(b"drop", b"no")
        store.delete(b"drop")

        flash2 = FlashSimulator(flash.size)
        flash2.load_raw(flash.get_raw())
        store2 = FlashKVStore(flash2)
        assert store2.get(b"keep") == b"yes"
        assert store2.get(b"drop") is None

    def test_recovery_partial_entry_magic_only(self):
        """Partial entry (magic written, nothing else) is ignored."""
        from kvstore import FlashKVStore
        flash, store = _make_store()
        store.put(b"safe", b"data")

        # Compute next write offset
        entry_size = ENTRY_HEADER_SIZE + 4 + 4  # b"safe" + b"data"
        next_off = PAGE_HEADER_SIZE + entry_size

        # Write only entry magic at next position (simulating crash mid-write)
        flash.write(next_off, ENTRY_MAGIC)

        flash2 = FlashSimulator(flash.size)
        flash2.load_raw(flash.get_raw())
        store2 = FlashKVStore(flash2)
        assert store2.get(b"safe") == b"data"
        assert len(store2.list_keys()) == 1

    def test_recovery_corrupted_crc(self):
        """Entry with bad CRC stops page scan; prior entries survive."""
        from kvstore import FlashKVStore
        flash, store = _make_store()
        store.put(b"k1", b"v1")
        store.put(b"k2", b"v2")
        store.put(b"k3", b"v3")

        # Corrupt CRC of entry 2
        e1_size = ENTRY_HEADER_SIZE + 2 + 2  # b"k1" + b"v1"
        e2_crc_off = PAGE_HEADER_SIZE + e1_size + 12  # byte 12 of entry header = CRC

        raw = bytearray(flash.get_raw())
        raw[e2_crc_off] ^= 0xFF  # flip all bits in first CRC byte
        flash2 = FlashSimulator(flash.size)
        flash2.load_raw(bytes(raw))
        store2 = FlashKVStore(flash2)

        # Entry 1 is before corruption => survives
        assert store2.get(b"k1") == b"v1"
        # Entries 2 and 3 lost (scan stops at corrupted entry on same page)
        assert store2.get(b"k2") is None
        assert store2.get(b"k3") is None

    def test_recovery_continues_operations(self):
        """After recovery, new operations work on the recovered store."""
        from kvstore import FlashKVStore
        flash, store = _make_store()
        store.put(b"old", b"value")

        flash2 = FlashSimulator(flash.size)
        flash2.load_raw(flash.get_raw())
        store2 = FlashKVStore(flash2)
        store2.put(b"new", b"entry")

        assert store2.get(b"old") == b"value"
        assert store2.get(b"new") == b"entry"

    def test_recovery_duplicate_valid_entries(self):
        """If crash left duplicate valid entries (same key, both state=VALID),
        recovery picks the entry on the page with higher sequence number,
        or the later offset on the same page."""
        from kvstore import FlashKVStore
        flash = FlashSimulator(2 * 4096)
        store = FlashKVStore(flash)
        store.format()

        store.put(b"dup", b"old_val")

        # Manually write a second valid entry for "dup" at the next position
        # without invalidating the first — simulating crash between
        # write-new and invalidate-old
        key = b"dup"
        value = b"new_val"
        key_hash = _ref_fnv1a_32(key)
        crc = _ref_compute_crc(len(key), len(value), key_hash, key, value)

        first_entry_size = ENTRY_HEADER_SIZE + 3 + 7  # "dup" + "old_val"
        write_pos = PAGE_HEADER_SIZE + first_entry_size

        entry = (ENTRY_MAGIC + bytes([0x0F]) + bytes([len(key)]) +
                 struct.pack('<III', len(value), key_hash, crc) +
                 key + value)
        flash.write(write_pos, entry)

        # Both entries valid on same page — recovery should pick later one
        flash2 = FlashSimulator(flash.size)
        flash2.load_raw(flash.get_raw())
        store2 = FlashKVStore(flash2)

        assert store2.get(b"dup") == b"new_val"


# ===================================================================
# 5. Compaction
# ===================================================================

class TestCompaction:
    def test_compaction_preserves_data(self):
        flash, store = _make_store(num_pages=8)
        store.put(b"name", b"Alice")
        store.put(b"age", b"30")
        store.put(b"city", b"NYC")
        store.put(b"name", b"Bob")  # overwrite
        store.put(b"job", b"eng")
        store.delete(b"age")

        store.compact()

        assert store.get(b"name") == b"Bob"
        assert store.get(b"age") is None
        assert store.get(b"city") == b"NYC"
        assert store.get(b"job") == b"eng"
        assert sorted(store.list_keys()) == [b"city", b"job", b"name"]

    def test_compaction_frees_space(self):
        flash, store = _make_store(num_pages=2)
        # Overwrite same key many times to consume flash space
        last_val = None
        for i in range(800):
            val = f"v{i}".encode()
            if not store.put(b"key", val):
                break
            last_val = val

        assert last_val is not None
        store.compact()
        assert store.get(b"key") == last_val

        # After compaction, lots of free space
        assert store.put(b"extra1", b"yes") is True
        assert store.put(b"extra2", b"also") is True
        assert store.get(b"extra1") == b"yes"
        assert store.get(b"extra2") == b"also"

    def test_compaction_erases_pages_with_dead_entries(self):
        """Compaction erases pages that had dead entries."""
        flash, store = _make_store()
        store.put(b"x", b"y")
        store.put(b"x", b"z")  # overwrite creates dead entry

        counts_before = list(flash.erase_counts)
        store.compact()

        # At least the page with the dead entry should have been erased
        any_erased = any(flash.erase_counts[i] > counts_before[i]
                         for i in range(flash.num_pages))
        assert any_erased, \
            f"Expected at least one page erase; counts before={counts_before}, after={list(flash.erase_counts)}"

    def test_compaction_page_header_erase_count(self):
        """Page header erase_count field matches actual erase count."""
        flash, store = _make_store()
        store.put(b"p", b"q")
        store.put(b"p", b"r")  # overwrite to create dead entry
        store.compact()

        # Find the active page after compaction
        for pn in range(flash.num_pages):
            base = pn * flash.page_size
            if flash.read(base, 4) == PAGE_MAGIC:
                status = flash.read(base + 4, 1)[0]
                if status == 0x0F:
                    raw = flash.read(base + 8, 4)
                    header_ec = struct.unpack_from('<I', raw, 0)[0]
                    assert header_ec == flash.erase_counts[pn], \
                        f"Page {pn}: header EC={header_ec} != flash EC={flash.erase_counts[pn]}"
                    break

    def test_recovery_after_compaction(self):
        from kvstore import FlashKVStore
        flash, store = _make_store()
        store.put(b"persist", b"yes")
        store.put(b"temp", b"no")
        store.delete(b"temp")
        store.compact()

        flash2 = FlashSimulator(flash.size)
        flash2.load_raw(flash.get_raw())
        store2 = FlashKVStore(flash2)
        assert store2.get(b"persist") == b"yes"
        assert store2.get(b"temp") is None
        assert sorted(store2.list_keys()) == [b"persist"]


# ===================================================================
# 6. Edge cases
# ===================================================================

class TestEdgeCases:
    def test_hash_collision(self):
        """Two keys with the same FNV-1a hash are stored independently."""
        from kvstore import FlashKVStore
        flash, store = _make_store()

        # Pre-computed FNV-1a 32-bit collision pair (both hash to 0x101e944b)
        key1 = b"40189"
        key2 = b"797186"
        assert key1 != key2
        assert _ref_fnv1a_32(key1) == _ref_fnv1a_32(key2)

        store.put(key1, b"val_a")
        store.put(key2, b"val_b")
        assert store.get(key1) == b"val_a"
        assert store.get(key2) == b"val_b"

        store.delete(key1)
        assert store.get(key1) is None
        assert store.get(key2) == b"val_b"

    def test_binary_key_and_value(self):
        """Keys and values can be arbitrary bytes."""
        flash, store = _make_store()
        key = bytes(range(1, 128))
        val = bytes(range(255, 0, -1))
        store.put(key, val)
        assert store.get(key) == val

    def test_many_deletes_then_compact(self):
        """Deleting many keys then compacting works."""
        flash, store = _make_store(num_pages=4)
        keys = [f"d{i:04d}".encode() for i in range(50)]
        for k in keys:
            store.put(k, b"data")
        for k in keys[:40]:
            store.delete(k)
        store.compact()

        for k in keys[:40]:
            assert store.get(k) is None
        for k in keys[40:]:
            assert store.get(k) == b"data"
        assert len(store.list_keys()) == 10

    def test_single_byte_key(self):
        flash, store = _make_store()
        store.put(b"\x01", b"one")
        assert store.get(b"\x01") == b"one"

    def test_overwrite_after_recovery(self):
        """Overwrite a key on a recovered store; old entry is invalidated."""
        from kvstore import FlashKVStore
        flash, store = _make_store()
        store.put(b"mut", b"orig")

        flash2 = FlashSimulator(flash.size)
        flash2.load_raw(flash.get_raw())
        store2 = FlashKVStore(flash2)
        store2.put(b"mut", b"changed")
        assert store2.get(b"mut") == b"changed"

        # Verify old entry on flash is invalidated
        old_state = flash2.read(PAGE_HEADER_SIZE + 2, 1)[0]
        assert old_state == 0x00

    def test_compact_empty_store(self):
        """Compacting an empty store does not crash."""
        flash, store = _make_store()
        store.compact()
        assert store.list_keys() == []
        assert store.put(b"after", b"compact") is True
        assert store.get(b"after") == b"compact"


# ===================================================================
# 7. Cross-compatibility with C reference implementation
# ===================================================================

@pytest.mark.skipif(not os.path.isfile(TICKV_TOOL),
                    reason="C reference tool not found")
class TestCrossCompatibility:
    """Verify Python implementation is binary-format-compatible with
    the C tickv_tool reference."""

    def _tmpfile(self):
        fd, path = tempfile.mkstemp(suffix='.bin')
        os.close(fd)
        return path

    def test_c_write_python_read(self):
        """Python reads a flash image created by the C tool."""
        from kvstore import FlashKVStore
        tmp = self._tmpfile()
        try:
            subprocess.run([TICKV_TOOL, 'init', tmp, '4'],
                           check=True, capture_output=True)
            subprocess.run([TICKV_TOOL, 'put', tmp, 'hello', 'world'],
                           check=True, capture_output=True)
            subprocess.run([TICKV_TOOL, 'put', tmp, 'foo', 'bar'],
                           check=True, capture_output=True)

            with open(tmp, 'rb') as f:
                data = f.read()
            flash = FlashSimulator(len(data))
            flash.load_raw(data)
            store = FlashKVStore(flash)

            assert store.get(b'hello') == b'world'
            assert store.get(b'foo') == b'bar'
            assert sorted(store.list_keys()) == [b'foo', b'hello']
        finally:
            os.unlink(tmp)

    def test_python_write_c_read(self):
        """C tool reads a flash image created by Python."""
        from kvstore import FlashKVStore
        flash = FlashSimulator(4 * 4096)
        store = FlashKVStore(flash)
        store.format()
        store.put(b'test_key', b'test_value')
        store.put(b'another', b'entry')

        tmp = self._tmpfile()
        try:
            with open(tmp, 'wb') as f:
                f.write(flash.get_raw())

            r1 = subprocess.run([TICKV_TOOL, 'get', tmp, 'test_key'],
                                capture_output=True, text=True)
            assert r1.stdout.strip() == 'test_value'

            r2 = subprocess.run([TICKV_TOOL, 'get', tmp, 'another'],
                                capture_output=True, text=True)
            assert r2.stdout.strip() == 'entry'
        finally:
            os.unlink(tmp)

    def test_c_overwrite_python_recovery(self):
        """Python correctly sees the latest value after C tool overwrites."""
        from kvstore import FlashKVStore
        tmp = self._tmpfile()
        try:
            subprocess.run([TICKV_TOOL, 'init', tmp, '4'],
                           check=True, capture_output=True)
            subprocess.run([TICKV_TOOL, 'put', tmp, 'key', 'old'],
                           check=True, capture_output=True)
            subprocess.run([TICKV_TOOL, 'put', tmp, 'key', 'new'],
                           check=True, capture_output=True)

            with open(tmp, 'rb') as f:
                data = f.read()
            flash = FlashSimulator(len(data))
            flash.load_raw(data)
            store = FlashKVStore(flash)

            assert store.get(b'key') == b'new'
        finally:
            os.unlink(tmp)

    def test_c_delete_python_recovery(self):
        """Python sees a key as deleted after C tool removes it."""
        from kvstore import FlashKVStore
        tmp = self._tmpfile()
        try:
            subprocess.run([TICKV_TOOL, 'init', tmp, '4'],
                           check=True, capture_output=True)
            subprocess.run([TICKV_TOOL, 'put', tmp, 'keep', 'yes'],
                           check=True, capture_output=True)
            subprocess.run([TICKV_TOOL, 'put', tmp, 'drop', 'no'],
                           check=True, capture_output=True)
            subprocess.run([TICKV_TOOL, 'delete', tmp, 'drop'],
                           check=True, capture_output=True)

            with open(tmp, 'rb') as f:
                data = f.read()
            flash = FlashSimulator(len(data))
            flash.load_raw(data)
            store = FlashKVStore(flash)

            assert store.get(b'keep') == b'yes'
            assert store.get(b'drop') is None
        finally:
            os.unlink(tmp)

    def test_python_write_c_dump_crc_ok(self):
        """C tool's dump command reports OK CRCs for Python-created entries."""
        from kvstore import FlashKVStore
        flash = FlashSimulator(4 * 4096)
        store = FlashKVStore(flash)
        store.format()
        for i in range(5):
            store.put(f'k{i}'.encode(), f'v{i}'.encode())

        tmp = self._tmpfile()
        try:
            with open(tmp, 'wb') as f:
                f.write(flash.get_raw())

            result = subprocess.run([TICKV_TOOL, 'dump', tmp],
                                    capture_output=True, text=True)
            assert 'crc=OK' in result.stdout
            assert 'crc=BAD' not in result.stdout
            for i in range(5):
                assert f'k{i}' in result.stdout
        finally:
            os.unlink(tmp)

    def test_c_compact_python_recovery(self):
        """Python recovers data from a C-compacted image."""
        from kvstore import FlashKVStore
        tmp = self._tmpfile()
        try:
            subprocess.run([TICKV_TOOL, 'init', tmp, '4'],
                           check=True, capture_output=True)
            for i in range(20):
                subprocess.run([TICKV_TOOL, 'put', tmp, 'counter', str(i)],
                               check=True, capture_output=True)
            subprocess.run([TICKV_TOOL, 'compact', tmp],
                           check=True, capture_output=True)

            with open(tmp, 'rb') as f:
                data = f.read()
            flash = FlashSimulator(len(data))
            flash.load_raw(data)
            store = FlashKVStore(flash)

            assert store.get(b'counter') == b'19'
        finally:
            os.unlink(tmp)

    def test_roundtrip_python_to_c_to_python(self):
        """Python write -> C tool modify -> Python recovery."""
        from kvstore import FlashKVStore
        flash = FlashSimulator(4 * 4096)
        store = FlashKVStore(flash)
        store.format()
        store.put(b'original', b'python_value')
        store.put(b'shared', b'initial')

        tmp = self._tmpfile()
        try:
            with open(tmp, 'wb') as f:
                f.write(flash.get_raw())

            # C tool modifies the image
            subprocess.run([TICKV_TOOL, 'put', tmp, 'c_added', 'from_c'],
                           check=True, capture_output=True)
            subprocess.run([TICKV_TOOL, 'put', tmp, 'shared', 'updated_by_c'],
                           check=True, capture_output=True)

            # Python reads the modified image
            with open(tmp, 'rb') as f:
                data = f.read()
            flash2 = FlashSimulator(len(data))
            flash2.load_raw(data)
            store2 = FlashKVStore(flash2)

            assert store2.get(b'original') == b'python_value'
            assert store2.get(b'c_added') == b'from_c'
            assert store2.get(b'shared') == b'updated_by_c'
        finally:
            os.unlink(tmp)


# ===================================================================
# 8. Crash-safe compaction
# ===================================================================

class TestCrashSafeCompaction:
    """Verify that power loss at any point during compact() does not
    lose data. This is the key expert-level requirement — the C reference
    is NOT crash-safe during compaction."""

    def _setup_dirty_store(self):
        """Create a store with dead entries across multiple pages."""
        flash = FlashSimulator(6 * 4096)
        from kvstore import FlashKVStore
        store = FlashKVStore(flash)
        store.format()

        # Write entries to fill multiple pages
        for i in range(40):
            store.put(f"k{i:03d}".encode(),
                      f"val_{i:03d}_{'x' * 60}".encode())

        # Create dead entries via deletes and overwrites
        for i in range(0, 25):
            store.delete(f"k{i:03d}".encode())
        for i in range(25, 35):
            store.put(f"k{i:03d}".encode(),
                      f"upd_{i:03d}_{'y' * 60}".encode())

        return flash, store

    def _get_live_data(self, store):
        keys = store.list_keys()
        return {k: store.get(k) for k in keys}

    def test_normal_compaction_preserves_data(self):
        """Compaction without crash preserves all live data."""
        flash, store = self._setup_dirty_store()
        live_before = self._get_live_data(store)
        assert len(live_before) > 0

        store.compact()

        live_after = self._get_live_data(store)
        assert live_after == live_before

    def test_crash_at_every_point_preserves_data(self):
        """Power loss at ANY write/erase op during compact() must not lose data."""
        from kvstore import FlashKVStore

        flash, store = self._setup_dirty_store()
        live_data = self._get_live_data(store)
        pre_raw = flash.get_raw()
        pre_erase_counts = list(flash.erase_counts)

        # Count total ops during normal compaction
        count_flash = FlashSimulator(len(pre_raw))
        count_flash.load_raw(pre_raw)
        count_flash.erase_counts = list(pre_erase_counts)
        counter = OpCountingFlash(count_flash)
        count_store = FlashKVStore(counter)
        count_store.compact()
        total_ops = counter.op_count

        assert total_ops > 5, f"Expected multiple ops during compaction, got {total_ops}"

        # Test crash at each point
        for crash_at in range(1, total_ops + 1):
            base = FlashSimulator(len(pre_raw))
            base.load_raw(pre_raw)
            base.erase_counts = list(pre_erase_counts)
            crashable = CrashableFlash(base, crash_at)

            crash_store = FlashKVStore(crashable)
            try:
                crash_store.compact()
            except CrashableFlash.PowerLoss:
                pass

            # Recover from crashed state
            recover_flash = FlashSimulator(len(pre_raw))
            recover_flash.load_raw(crashable.get_raw())
            recover_store = FlashKVStore(recover_flash)

            recovered_data = self._get_live_data(recover_store)
            for k, v in live_data.items():
                assert recovered_data.get(k) == v, \
                    (f"Data loss at crash point {crash_at}/{total_ops}: "
                     f"key {k!r} expected {v!r} got {recovered_data.get(k)!r}")

    def test_post_crash_store_is_functional(self):
        """After crash recovery from interrupted compaction,
        the store supports new put/get/delete operations."""
        from kvstore import FlashKVStore

        flash, store = self._setup_dirty_store()
        live_data = self._get_live_data(store)
        pre_raw = flash.get_raw()
        pre_erase_counts = list(flash.erase_counts)

        # Crash after a few ops into compaction
        base = FlashSimulator(len(pre_raw))
        base.load_raw(pre_raw)
        base.erase_counts = list(pre_erase_counts)
        crashable = CrashableFlash(base, 3)

        crash_store = FlashKVStore(crashable)
        try:
            crash_store.compact()
        except CrashableFlash.PowerLoss:
            pass

        # Recover and perform new operations
        recover_flash = FlashSimulator(len(pre_raw))
        recover_flash.load_raw(crashable.get_raw())
        recover_store = FlashKVStore(recover_flash)

        # New operations work
        recover_store.put(b"post_crash", b"works")
        assert recover_store.get(b"post_crash") == b"works"

        # Old data intact
        for k, v in live_data.items():
            assert recover_store.get(k) == v

    def test_crash_during_active_page_compaction(self):
        """Crash while compacting the active page preserves data."""
        from kvstore import FlashKVStore

        flash = FlashSimulator(4 * 4096)
        store = FlashKVStore(flash)
        store.format()

        # Create dead entries on the active page via overwrites
        for i in range(10):
            store.put(b"akey", f"val_{i}".encode())

        live_data = self._get_live_data(store)
        pre_raw = flash.get_raw()
        pre_erase_counts = list(flash.erase_counts)

        # Count ops
        count_flash = FlashSimulator(len(pre_raw))
        count_flash.load_raw(pre_raw)
        count_flash.erase_counts = list(pre_erase_counts)
        counter = OpCountingFlash(count_flash)
        count_store = FlashKVStore(counter)
        count_store.compact()
        total_ops = counter.op_count

        if total_ops > 0:
            for crash_at in range(1, total_ops + 1):
                base = FlashSimulator(len(pre_raw))
                base.load_raw(pre_raw)
                base.erase_counts = list(pre_erase_counts)
                crashable = CrashableFlash(base, crash_at)

                crash_store = FlashKVStore(crashable)
                try:
                    crash_store.compact()
                except CrashableFlash.PowerLoss:
                    pass

                recover_flash = FlashSimulator(len(pre_raw))
                recover_flash.load_raw(crashable.get_raw())
                recover_store = FlashKVStore(recover_flash)

                recovered = self._get_live_data(recover_store)
                for k, v in live_data.items():
                    assert recovered.get(k) == v, \
                        f"Active page crash at {crash_at}: lost {k!r}"


# ===================================================================
# 9. Wear-leveling
# ===================================================================

class TestWearLeveling:
    """Verify that page activation prefers pages with lowest erase count."""

    def _find_active_page(self, flash):
        """Find the currently active page number."""
        for pn in range(flash.num_pages):
            base = pn * flash.page_size
            hdr = flash.read(base, 5)
            if hdr[:4] == PAGE_MAGIC and hdr[4] == 0x0F:
                return pn
        return None

    def test_page_activation_prefers_low_erase_count(self):
        """When multiple free pages exist, the one with lowest
        erase count is activated next."""
        from kvstore import FlashKVStore
        flash = FlashSimulator(4 * 4096)

        # Pre-wear pages to create uneven wear
        for _ in range(10):
            flash.erase_page(1)
        for _ in range(5):
            flash.erase_page(2)
        # After pre-wear: p0=0, p1=10, p2=5, p3=0

        store = FlashKVStore(flash)
        store.format()
        # After format (erases all): p0=1, p1=11, p2=6, p3=1
        # Page 0 is active (sequence 0)

        # Fill page 0 to trigger switch to next page
        # Max entry: fills entire page leaving no room for another entry
        val = b"X" * (4096 - PAGE_HEADER_SIZE - ENTRY_HEADER_SIZE - 1)
        store.put(b"a", val)  # fills page 0

        # Next put triggers page switch
        store.put(b"b", b"trigger_switch")

        # Among free pages {1, 2, 3}: p1=11, p2=6, p3=1
        # Wear-leveling should pick p3 (lowest erase count = 1)
        active = self._find_active_page(flash)
        assert active == 3, \
            f"Expected page 3 (EC=1) to be activated, got page {active} " \
            f"(erase_counts={flash.erase_counts[:4]})"

    def test_wear_leveling_second_switch(self):
        """After two page switches, the second-lowest EC page is chosen."""
        from kvstore import FlashKVStore
        flash = FlashSimulator(4 * 4096)

        # Pre-wear to create distinct erase counts
        for _ in range(15):
            flash.erase_page(1)
        for _ in range(10):
            flash.erase_page(2)
        for _ in range(5):
            flash.erase_page(3)
        # Pre-wear: p0=0, p1=15, p2=10, p3=5

        store = FlashKVStore(flash)
        store.format()
        # Post-format: p0=1, p1=16, p2=11, p3=6

        # Fill page 0, switch to page with lowest EC among {1,2,3}
        val = b"X" * (4096 - PAGE_HEADER_SIZE - ENTRY_HEADER_SIZE - 1)
        store.put(b"a", val)
        store.put(b"b", b"switch1")

        first_active = self._find_active_page(flash)
        assert first_active == 3, \
            f"First switch: expected page 3 (EC=6), got {first_active}"

        # Fill page 3 — entry "c" won't fit (24 bytes used by "b"),
        # triggers switch. Among free pages {1,2}: p2 (EC=11) < p1 (EC=16)
        val2 = b"Y" * (4096 - PAGE_HEADER_SIZE - ENTRY_HEADER_SIZE - 1)
        store.put(b"c", val2)

        # Check immediately after the switch (before any further writes
        # that might trigger another page switch)
        second_active = self._find_active_page(flash)
        assert second_active == 2, \
            f"Second switch: expected page 2 (EC=11), got {second_active}"

    def test_erase_count_restored_from_page_headers(self):
        """After recovery, erase counts are restored from page headers
        so that wear-leveling decisions survive power cycles."""
        from kvstore import FlashKVStore
        flash = FlashSimulator(4 * 4096)

        # Pre-wear page 1 extensively
        for _ in range(20):
            flash.erase_page(1)

        store = FlashKVStore(flash)
        store.format()
        store.put(b"data", b"value")

        # Simulate power cycle
        raw = flash.get_raw()
        flash2 = FlashSimulator(flash.size)
        flash2.load_raw(raw)
        # flash2.erase_counts are all 0 from fresh FlashSimulator

        store2 = FlashKVStore(flash2)
        # Recovery should have restored erase counts from page headers

        # Fill page 0 to trigger switch
        val = b"Z" * (4096 - PAGE_HEADER_SIZE - ENTRY_HEADER_SIZE - 5)
        store2.put(b"fill", val)
        store2.put(b"next", b"entry")

        # Should NOT pick page 1 (high EC from pre-wear)
        active = self._find_active_page(flash2)
        assert active != 1, \
            f"Page 1 (high EC) should not be chosen; got active={active}"
