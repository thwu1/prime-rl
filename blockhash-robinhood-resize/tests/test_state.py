"""

Tests for the cache-line-aligned hash table with incremental resizing.
Loads /app/libblockht.so via ctypes and exercises correctness, structural,
and algorithmic properties.
"""

import ctypes
import hashlib
import struct
import subprocess
import pytest


# ---------------------------------------------------------------------------
# Build and load
# ---------------------------------------------------------------------------

def _build():
    r = subprocess.run(["make", "-C", "/app", "clean"], capture_output=True)
    r = subprocess.run(["make", "-C", "/app"], capture_output=True)
    assert r.returncode == 0, f"Build failed:\n{r.stderr.decode()}"


@pytest.fixture(scope="session")
def lib():
    _build()
    L = ctypes.CDLL("/app/libblockht.so")

    L.bht_create.restype = ctypes.c_void_p
    L.bht_create.argtypes = [ctypes.c_uint32]

    L.bht_destroy.restype = None
    L.bht_destroy.argtypes = [ctypes.c_void_p]

    L.bht_insert.restype = ctypes.c_int
    L.bht_insert.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
        ctypes.c_void_p, ctypes.c_uint32,
    ]

    L.bht_lookup.restype = ctypes.c_int
    L.bht_lookup.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32),
    ]

    L.bht_delete.restype = ctypes.c_int
    L.bht_delete.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]

    L.bht_count.restype = ctypes.c_uint64
    L.bht_count.argtypes = [ctypes.c_void_p]

    L.bht_load_factor.restype = ctypes.c_double
    L.bht_load_factor.argtypes = [ctypes.c_void_p]

    L.bht_memory_usage.restype = ctypes.c_uint64
    L.bht_memory_usage.argtypes = [ctypes.c_void_p]

    L.bht_is_resizing.restype = ctypes.c_int
    L.bht_is_resizing.argtypes = [ctypes.c_void_p]

    L.bht_avg_probe_distance.restype = ctypes.c_double
    L.bht_avg_probe_distance.argtypes = [ctypes.c_void_p]

    L.bht_verify_alignment.restype = ctypes.c_int
    L.bht_verify_alignment.argtypes = [ctypes.c_void_p]

    return L


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ins(lib, ht, key: bytes, val: bytes):
    return lib.bht_insert(ht, key, len(key), val, len(val))


def _get(lib, ht, key: bytes):
    vp = ctypes.c_void_p()
    vl = ctypes.c_uint32()
    ret = lib.bht_lookup(ht, key, len(key), ctypes.byref(vp), ctypes.byref(vl))
    if ret != 0:
        return None
    if vl.value == 0:
        return b""
    return ctypes.string_at(vp.value, vl.value)


def _del(lib, ht, key: bytes):
    return lib.bht_delete(ht, key, len(key))


# ---------------------------------------------------------------------------
# 1. Basic CRUD
# ---------------------------------------------------------------------------

class TestBasicCRUD:
    def test_create_destroy(self, lib):
        ht = lib.bht_create(16)
        assert ht is not None
        assert lib.bht_count(ht) == 0
        lib.bht_destroy(ht)

    def test_insert_and_lookup(self, lib):
        ht = lib.bht_create(16)
        assert _ins(lib, ht, b"hello", b"world") == 0
        assert lib.bht_count(ht) == 1
        assert _get(lib, ht, b"hello") == b"world"
        lib.bht_destroy(ht)

    def test_multiple_inserts(self, lib):
        ht = lib.bht_create(128)
        for i in range(50):
            assert _ins(lib, ht, f"key_{i}".encode(), f"val_{i}".encode()) == 0
        assert lib.bht_count(ht) == 50
        for i in range(50):
            assert _get(lib, ht, f"key_{i}".encode()) == f"val_{i}".encode()
        lib.bht_destroy(ht)

    def test_delete(self, lib):
        ht = lib.bht_create(16)
        _ins(lib, ht, b"foo", b"bar")
        assert lib.bht_count(ht) == 1
        assert _del(lib, ht, b"foo") == 0
        assert lib.bht_count(ht) == 0
        assert _get(lib, ht, b"foo") is None
        lib.bht_destroy(ht)

    def test_delete_nonexistent(self, lib):
        ht = lib.bht_create(16)
        assert _del(lib, ht, b"nope") == -1
        lib.bht_destroy(ht)

    def test_lookup_nonexistent(self, lib):
        ht = lib.bht_create(16)
        assert _get(lib, ht, b"nope") is None
        lib.bht_destroy(ht)


# ---------------------------------------------------------------------------
# 2. Overwrite semantics
# ---------------------------------------------------------------------------

class TestOverwrite:
    def test_overwrite_same_size(self, lib):
        ht = lib.bht_create(16)
        _ins(lib, ht, b"key1", b"AAAA")
        _ins(lib, ht, b"key1", b"BBBB")
        assert lib.bht_count(ht) == 1
        assert _get(lib, ht, b"key1") == b"BBBB"
        lib.bht_destroy(ht)

    def test_overwrite_different_size(self, lib):
        ht = lib.bht_create(16)
        _ins(lib, ht, b"k", b"short")
        _ins(lib, ht, b"k", b"a much longer replacement value")
        assert lib.bht_count(ht) == 1
        assert _get(lib, ht, b"k") == b"a much longer replacement value"
        lib.bht_destroy(ht)

    def test_overwrite_to_empty_value(self, lib):
        ht = lib.bht_create(16)
        _ins(lib, ht, b"k", b"nonempty")
        _ins(lib, ht, b"k", b"")
        assert lib.bht_count(ht) == 1
        assert _get(lib, ht, b"k") == b""
        lib.bht_destroy(ht)


# ---------------------------------------------------------------------------
# 3. Variable-length keys
# ---------------------------------------------------------------------------

class TestVariableLengthKeys:
    def test_single_byte_keys(self, lib):
        ht = lib.bht_create(512)
        for i in range(256):
            _ins(lib, ht, bytes([i]), f"v{i}".encode())
        for i in range(256):
            assert _get(lib, ht, bytes([i])) == f"v{i}".encode()
        lib.bht_destroy(ht)

    def test_long_keys(self, lib):
        ht = lib.bht_create(64)
        pairs = []
        for i in range(20):
            key = hashlib.sha256(str(i).encode()).hexdigest().encode() * 4   # 256 B
            val = hashlib.sha256(f"val_{i}".encode()).digest() * 16          # 512 B
            pairs.append((key, val))
            assert _ins(lib, ht, key, val) == 0
        for k, v in pairs:
            assert _get(lib, ht, k) == v
        lib.bht_destroy(ht)

    def test_mixed_length_keys(self, lib):
        ht = lib.bht_create(256)
        entries = {}
        for i in range(100):
            klen = (i % 50) + 1
            key = hashlib.md5(str(i).encode()).hexdigest()[:klen].encode()
            val = f"v{i}_{klen}".encode()
            entries[key] = val
            _ins(lib, ht, key, val)
        for key, expected in entries.items():
            assert _get(lib, ht, key) == expected
        lib.bht_destroy(ht)


# ---------------------------------------------------------------------------
# 4. Large-scale correctness
# ---------------------------------------------------------------------------

class TestLargeScale:
    def test_200k_insert_lookup_delete(self, lib):
        ht = lib.bht_create(256)
        N = 200_000
        for i in range(N):
            k = struct.pack(">I", i)
            v = struct.pack(">Q", i * 7 + 13)
            assert _ins(lib, ht, k, v) == 0
        assert lib.bht_count(ht) == N

        for i in range(N):
            k = struct.pack(">I", i)
            assert _get(lib, ht, k) == struct.pack(">Q", i * 7 + 13)

        # Delete even-indexed keys
        for i in range(0, N, 2):
            assert _del(lib, ht, struct.pack(">I", i)) == 0
        assert lib.bht_count(ht) == N // 2

        # Verify survivors and deletions
        for i in range(N):
            k = struct.pack(">I", i)
            val = _get(lib, ht, k)
            if i % 2 == 0:
                assert val is None, f"Key {i} should have been deleted"
            else:
                assert val == struct.pack(">Q", i * 7 + 13), f"Wrong value at key {i}"
        lib.bht_destroy(ht)


# ---------------------------------------------------------------------------
# 5. Block alignment
# ---------------------------------------------------------------------------

class TestBlockAlignment:
    def test_alignment_empty(self, lib):
        ht = lib.bht_create(128)
        assert lib.bht_verify_alignment(ht) == 1
        lib.bht_destroy(ht)

    def test_alignment_populated(self, lib):
        ht = lib.bht_create(128)
        for i in range(100):
            _ins(lib, ht, f"a{i}".encode(), b"x")
        assert lib.bht_verify_alignment(ht) == 1
        lib.bht_destroy(ht)


# ---------------------------------------------------------------------------
# 6. Probe distance bounds
# ---------------------------------------------------------------------------

class TestProbeDistance:
    def test_avg_probe_distance_bounded(self, lib):
        """At ~61% load (well under 70%), avg probe distance must be <= 2.0."""
        ht = lib.bht_create(8192)
        target = 5000                     # 5000 / 8192 ≈ 0.61
        for i in range(target):
            _ins(lib, ht, struct.pack(">Q", i), b"v")
        avg = lib.bht_avg_probe_distance(ht)
        assert avg <= 2.0, f"avg probe distance {avg:.3f} exceeds 2.0"
        lib.bht_destroy(ht)

    def test_probe_distance_at_70pct(self, lib):
        """At ~68% load, avg probe distance must still be <= 2.0."""
        cap = 16384
        target = int(cap * 0.68)          # 11141
        ht = lib.bht_create(cap)
        for i in range(target):
            _ins(lib, ht, struct.pack(">Q", i), b"v")
        avg = lib.bht_avg_probe_distance(ht)
        assert avg <= 2.0, f"avg probe distance {avg:.3f} exceeds 2.0 at 68%% load"
        lib.bht_destroy(ht)


# ---------------------------------------------------------------------------
# 7. Incremental resize
# ---------------------------------------------------------------------------

class TestIncrementalResize:
    def test_resize_triggers(self, lib):
        """bht_is_resizing must become 1 after enough inserts."""
        ht = lib.bht_create(256)
        saw = False
        for i in range(2000):
            _ins(lib, ht, struct.pack(">I", i), b"v")
            if lib.bht_is_resizing(ht):
                saw = True
                break
        assert saw, "bht_is_resizing never returned 1"
        lib.bht_destroy(ht)

    def test_correctness_during_resize(self, lib):
        """All previously inserted entries remain accessible mid-resize."""
        ht = lib.bht_create(2048)
        keys = []
        found_resize = False
        for i in range(4000):
            k = struct.pack(">I", i)
            v = struct.pack(">Q", i * 3)
            _ins(lib, ht, k, v)
            keys.append((k, v))
            if lib.bht_is_resizing(ht) and not found_resize:
                found_resize = True
                # Verify every key so far while we are mid-resize
                for kk, vv in keys:
                    assert _get(lib, ht, kk) == vv, "Entry inaccessible during resize"
                # Insert a few more while still resizing to exercise dual-table ops
                for j in range(i + 1, i + 65):
                    k2 = struct.pack(">I", j)
                    v2 = struct.pack(">Q", j * 3)
                    _ins(lib, ht, k2, v2)
                    keys.append((k2, v2))
                break
        assert found_resize, "Resize never triggered"
        # Verify all keys after resize batch
        for kk, vv in keys:
            assert _get(lib, ht, kk) == vv
        lib.bht_destroy(ht)

    def test_resize_completes(self, lib):
        """After enough mutations, resize should complete."""
        ht = lib.bht_create(256)
        for i in range(10000):
            _ins(lib, ht, struct.pack(">I", i), b"v")
        # At this point, the original resize should have completed
        # (more resizes may have happened and completed since then)
        # Just verify correctness
        for i in range(10000):
            assert _get(lib, ht, struct.pack(">I", i)) == b"v"
        lib.bht_destroy(ht)


# ---------------------------------------------------------------------------
# 8. Delete during resize
# ---------------------------------------------------------------------------

class TestDeleteDuringResize:
    def test_delete_while_resizing(self, lib):
        ht = lib.bht_create(2048)
        N = 3000
        for i in range(N):
            _ins(lib, ht, struct.pack(">I", i), struct.pack(">I", i))

        # Continue inserting to trigger resize
        resizing = False
        extra = N
        while not resizing and extra < N + 5000:
            _ins(lib, ht, struct.pack(">I", extra), struct.pack(">I", extra))
            resizing = lib.bht_is_resizing(ht)
            extra += 1

        if resizing:
            # Delete even-indexed entries while mid-resize
            for d in range(0, 200, 2):
                ret = _del(lib, ht, struct.pack(">I", d))
                assert ret == 0, f"Delete of key {d} failed during resize"

            # Deleted entries must be gone
            for d in range(0, 200, 2):
                assert _get(lib, ht, struct.pack(">I", d)) is None

            # Odd-indexed entries must remain
            for d in range(1, 200, 2):
                assert _get(lib, ht, struct.pack(">I", d)) == struct.pack(">I", d)

        lib.bht_destroy(ht)


# ---------------------------------------------------------------------------
# 9. Memory overhead
# ---------------------------------------------------------------------------

class TestMemoryOverhead:
    def test_overhead_per_entry(self, lib):
        """Structural overhead per entry must be <= 32 bytes (not mid-resize)."""
        cap = 16384
        N = int(cap * 0.68)              # ~11141 entries → 68% load, under resize threshold
        ht = lib.bht_create(cap)
        total_kv = 0
        for i in range(N):
            k = struct.pack(">I", i)      # 4 bytes
            v = struct.pack(">Q", i)      # 8 bytes
            _ins(lib, ht, k, v)
            total_kv += 12

        assert lib.bht_is_resizing(ht) == 0, "Table should not be resizing"
        mem = lib.bht_memory_usage(ht)
        overhead = (mem - total_kv) / N
        assert overhead <= 32, f"Per-entry overhead {overhead:.1f} B exceeds 32 B"
        lib.bht_destroy(ht)


# ---------------------------------------------------------------------------
# 10. Insert-delete-reinsert stress
# ---------------------------------------------------------------------------

class TestStress:
    def test_reinsert_after_delete(self, lib):
        """Repeated insert→delete→reinsert cycles must not leak or corrupt."""
        ht = lib.bht_create(256)
        for cycle in range(5):
            for i in range(500):
                _ins(lib, ht, struct.pack(">H", i), struct.pack(">H", cycle))
            assert lib.bht_count(ht) == 500
            for i in range(500):
                assert _get(lib, ht, struct.pack(">H", i)) == struct.pack(">H", cycle)
            for i in range(500):
                assert _del(lib, ht, struct.pack(">H", i)) == 0
            assert lib.bht_count(ht) == 0
        lib.bht_destroy(ht)
