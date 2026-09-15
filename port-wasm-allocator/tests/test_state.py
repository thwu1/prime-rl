
"""
Tests for the native port of walloc — the WebAssembly malloc implementation.

Loads /app/libwalloc.so via ctypes and exercises the walloc_* API:
  - Lifecycle (init / destroy / re-init)
  - Small-object size classes (all 10)
  - Large-object allocation and coalescing
  - realloc (same-class, cross-class, small↔large, data integrity)
  - calloc (zero-initialization, including reused dirty memory)
  - Stats accuracy (heap_pages, freelist counts)
  - Stress test (random alloc/free pattern)
"""

import ctypes
import os
import random
import pytest

LIB_PATH = "/app/libwalloc.so"
WALLOC_PAGE_SIZE = 65536


# ---------- ctypes setup ----------

class WallocStats(ctypes.Structure):
    _fields_ = [
        ("heap_pages", ctypes.c_size_t),
        ("heap_size_bytes", ctypes.c_size_t),
        ("free_large_count", ctypes.c_size_t),
        ("free_large_total_bytes", ctypes.c_size_t),
        ("small_free_counts", ctypes.c_size_t * 10),
        ("small_free_total", ctypes.c_size_t),
    ]


def _load_lib():
    assert os.path.exists(LIB_PATH), f"Library not found: {LIB_PATH}"
    lib = ctypes.CDLL(LIB_PATH)

    lib.walloc_init.argtypes = [ctypes.c_size_t]
    lib.walloc_init.restype = ctypes.c_int

    lib.walloc_malloc.argtypes = [ctypes.c_size_t]
    lib.walloc_malloc.restype = ctypes.c_void_p

    lib.walloc_free.argtypes = [ctypes.c_void_p]
    lib.walloc_free.restype = None

    lib.walloc_realloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    lib.walloc_realloc.restype = ctypes.c_void_p

    lib.walloc_calloc.argtypes = [ctypes.c_size_t, ctypes.c_size_t]
    lib.walloc_calloc.restype = ctypes.c_void_p

    lib.walloc_get_stats.argtypes = [ctypes.POINTER(WallocStats)]
    lib.walloc_get_stats.restype = ctypes.c_int

    lib.walloc_destroy.argtypes = []
    lib.walloc_destroy.restype = None

    return lib


_lib = _load_lib()


@pytest.fixture(autouse=True)
def _cleanup():
    """Ensure walloc_destroy is called after every test."""
    yield
    _lib.walloc_destroy()


# ---------- helpers ----------

def _init(pages=4):
    rc = _lib.walloc_init(pages)
    assert rc == 0, "walloc_init failed"


def _write_pattern(addr, size, byte=0xAB):
    ctypes.memset(addr, byte, size)


def _read_bytes(addr, size):
    return bytes((ctypes.c_ubyte * size).from_address(addr))


def _get_stats():
    s = WallocStats()
    rc = _lib.walloc_get_stats(ctypes.byref(s))
    assert rc == 0, "walloc_get_stats failed"
    return s


# ---------- tests ----------

class TestInit:
    def test_init_succeeds(self):
        _init(2)

    def test_init_stats(self):
        _init(2)
        _ = _lib.walloc_malloc(8)  # force internal setup
        s = _get_stats()
        assert s.heap_pages >= 2
        assert s.heap_size_bytes == s.heap_pages * WALLOC_PAGE_SIZE

    def test_destroy_is_idempotent(self):
        _init(2)
        _lib.walloc_destroy()
        _lib.walloc_destroy()  # must not crash

    def test_reinit_after_destroy(self):
        _init(2)
        p = _lib.walloc_malloc(64)
        assert p
        _lib.walloc_destroy()
        _init(4)
        p2 = _lib.walloc_malloc(64)
        assert p2


class TestMallocFree:
    def test_basic_alloc(self):
        _init()
        p = _lib.walloc_malloc(100)
        assert p
        _write_pattern(p, 100)
        assert _read_bytes(p, 100) == bytes([0xAB] * 100)
        _lib.walloc_free(p)

    def test_free_null(self):
        _init()
        _lib.walloc_free(None)  # must not crash

    def test_malloc_zero(self):
        _init()
        p = _lib.walloc_malloc(0)
        # implementation-defined; walloc returns a valid small allocation
        if p:
            _lib.walloc_free(p)

    def test_small_size_classes(self):
        """Allocate objects that hit each of the 10 size classes."""
        _init(8)
        # granule counts: 1,2,3,4,5,6,8,10,16,32  (8 bytes per granule)
        test_sizes = [1, 9, 17, 25, 33, 41, 49, 65, 100, 200]
        ptrs = []
        for sz in test_sizes:
            p = _lib.walloc_malloc(sz)
            assert p, f"malloc({sz}) returned NULL"
            assert p % 8 == 0, f"pointer not 8-byte aligned for size {sz}"
            _write_pattern(p, sz, sz & 0xFF)
            assert all(b == (sz & 0xFF) for b in _read_bytes(p, sz))
            ptrs.append(p)
        for p in ptrs:
            _lib.walloc_free(p)

    def test_large_objects(self):
        _init(8)
        sizes = [512, 1024, 4096, 16384, 60000]
        ptrs = []
        for sz in sizes:
            p = _lib.walloc_malloc(sz)
            assert p, f"malloc({sz}) returned NULL"
            _write_pattern(p, sz, 0x55)
            assert all(b == 0x55 for b in _read_bytes(p, sz))
            ptrs.append(p)
        for p in ptrs:
            _lib.walloc_free(p)

    def test_many_small_then_large(self):
        _init(16)
        smalls = []
        for _ in range(100):
            p = _lib.walloc_malloc(16)
            assert p
            smalls.append(p)
        big = _lib.walloc_malloc(32768)
        assert big
        _write_pattern(big, 32768, 0xCC)
        assert all(b == 0xCC for b in _read_bytes(big, 32768))
        _lib.walloc_free(big)
        for p in smalls:
            _lib.walloc_free(p)


class TestRealloc:
    def test_null_ptr_is_malloc(self):
        _init()
        p = _lib.walloc_realloc(None, 100)
        assert p
        _write_pattern(p, 100, 0x42)
        _lib.walloc_free(p)

    def test_zero_size_frees(self):
        _init()
        p = _lib.walloc_malloc(100)
        assert p
        _lib.walloc_realloc(p, 0)
        # after this, p is freed; we just verify no crash

    def test_same_size_class_returns_same_ptr(self):
        _init()
        p = _lib.walloc_malloc(20)  # GRANULES_3 (24 bytes)
        assert p
        _write_pattern(p, 20, 0x33)
        p2 = _lib.walloc_realloc(p, 22)  # still GRANULES_3
        assert p2 == p, "same-class realloc should return same pointer"
        assert _read_bytes(p2, 20) == bytes([0x33] * 20)
        _lib.walloc_free(p2)

    def test_grow_small_to_large(self):
        _init(8)
        p = _lib.walloc_malloc(32)
        assert p
        pattern = bytes(range(32))
        ctypes.memmove(p, pattern, 32)
        p2 = _lib.walloc_realloc(p, 1024)
        assert p2
        assert _read_bytes(p2, 32) == pattern
        _lib.walloc_free(p2)

    def test_shrink_large_to_small(self):
        _init(8)
        p = _lib.walloc_malloc(1024)
        assert p
        pattern = bytes(range(32))
        ctypes.memmove(p, pattern, 32)
        p2 = _lib.walloc_realloc(p, 32)
        assert p2
        assert _read_bytes(p2, 32) == pattern
        _lib.walloc_free(p2)

    def test_grow_large_to_larger(self):
        _init(16)
        p = _lib.walloc_malloc(512)
        assert p
        pattern = bytes([i & 0xFF for i in range(512)])
        ctypes.memmove(p, pattern, 512)
        p2 = _lib.walloc_realloc(p, 4096)
        assert p2
        assert _read_bytes(p2, 512) == pattern
        _lib.walloc_free(p2)

    def test_shrink_large_in_place(self):
        """Shrinking a large object within same allocation returns same ptr."""
        _init(8)
        p = _lib.walloc_malloc(2048)
        assert p
        _write_pattern(p, 64, 0xEE)
        p2 = _lib.walloc_realloc(p, 512)
        assert p2 == p, "shrinking large object should return same pointer"
        assert _read_bytes(p2, 64) == bytes([0xEE] * 64)
        _lib.walloc_free(p2)

    def test_data_integrity_chain(self):
        """Realloc through multiple size transitions preserving initial data."""
        _init(16)
        p = _lib.walloc_malloc(8)
        assert p
        ctypes.memmove(p, b"ABCDEFGH", 8)

        for new_size in [16, 32, 128, 512, 4096]:
            p = _lib.walloc_realloc(p, new_size)
            assert p, f"realloc to {new_size} returned NULL"
            assert _read_bytes(p, 8) == b"ABCDEFGH", \
                f"data corrupted at size {new_size}"

        # shrink back
        p = _lib.walloc_realloc(p, 32)
        assert p
        assert _read_bytes(p, 8) == b"ABCDEFGH"
        _lib.walloc_free(p)


class TestCalloc:
    def test_zeroed(self):
        _init()
        p = _lib.walloc_calloc(10, 100)
        assert p
        assert _read_bytes(p, 1000) == bytes(1000)
        _lib.walloc_free(p)

    def test_zeroed_after_dirty(self):
        """calloc must zero memory even when reusing freed dirty blocks."""
        _init(4)
        p1 = _lib.walloc_malloc(200)
        assert p1
        _write_pattern(p1, 200, 0xFF)
        _lib.walloc_free(p1)
        p2 = _lib.walloc_calloc(1, 200)
        assert p2
        data = _read_bytes(p2, 200)
        assert data == bytes(200), "calloc returned non-zero memory"
        _lib.walloc_free(p2)

    def test_overflow_returns_null(self):
        _init()
        p = _lib.walloc_calloc(ctypes.c_size_t(-1).value, 2)
        assert p is None or p == 0


class TestStats:
    def test_heap_pages(self):
        _init(4)
        _ = _lib.walloc_malloc(8)
        s = _get_stats()
        assert s.heap_pages >= 4
        assert s.heap_size_bytes == s.heap_pages * WALLOC_PAGE_SIZE

    def test_free_large_tracking(self):
        _init(8)
        p = _lib.walloc_malloc(512)
        assert p
        _lib.walloc_free(p)
        s = _get_stats()
        assert s.free_large_count >= 1
        assert s.free_large_total_bytes >= 512

    def test_small_free_tracking(self):
        _init(4)
        ptrs = [_lib.walloc_malloc(8) for _ in range(5)]
        for p in ptrs:
            _lib.walloc_free(p)
        s = _get_stats()
        assert s.small_free_total >= 5

    def test_consistency(self):
        _init(4)
        _ = _lib.walloc_malloc(8)
        s = _get_stats()
        total = sum(s.small_free_counts[i] for i in range(10))
        assert total == s.small_free_total


class TestStress:
    def test_random_alloc_free(self):
        _init(32)
        rng = random.Random(42)
        ptrs = []
        for _ in range(1000):
            if ptrs and rng.random() < 0.4:
                idx = rng.randint(0, len(ptrs) - 1)
                _lib.walloc_free(ptrs[idx])
                ptrs.pop(idx)
            else:
                sz = rng.randint(1, 8192)
                p = _lib.walloc_malloc(sz)
                assert p, f"malloc({sz}) returned NULL"
                ctypes.memset(p, sz & 0xFF, min(sz, 1))
                ptrs.append(p)
        for p in ptrs:
            _lib.walloc_free(p)

    def test_realloc_stress(self):
        _init(32)
        rng = random.Random(99)
        ptrs = []
        for _ in range(500):
            if ptrs and rng.random() < 0.3:
                idx = rng.randint(0, len(ptrs) - 1)
                old_p, old_sz = ptrs[idx]
                new_sz = rng.randint(1, 4096)
                new_p = _lib.walloc_realloc(old_p, new_sz)
                assert new_p, f"realloc({old_sz} -> {new_sz}) returned NULL"
                ptrs[idx] = (new_p, new_sz)
            elif ptrs and rng.random() < 0.5:
                idx = rng.randint(0, len(ptrs) - 1)
                _lib.walloc_free(ptrs[idx][0])
                ptrs.pop(idx)
            else:
                sz = rng.randint(1, 4096)
                p = _lib.walloc_malloc(sz)
                assert p, f"malloc({sz}) returned NULL"
                ptrs.append((p, sz))
        for p, _ in ptrs:
            _lib.walloc_free(p)

    def test_alignment(self):
        """All allocations must be at least 8-byte aligned."""
        _init(8)
        for sz in [1, 3, 7, 8, 15, 16, 24, 31, 32, 64, 100, 256, 512, 1024]:
            p = _lib.walloc_malloc(sz)
            assert p
            assert p % 8 == 0, f"alloc of {sz} bytes not 8-byte aligned: {p:#x}"
            _lib.walloc_free(p)
