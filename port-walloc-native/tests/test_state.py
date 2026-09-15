
"""
Tests for the native port of walloc (WebAssembly malloc).

Validates: compilation, basic allocation, malloc_usable_size for all 10 size
classes, realloc across all transition types, stress tests, and data integrity.
"""

import ctypes
import subprocess
import os
import random
import pytest


@pytest.fixture(scope="session")
def lib():
    """Compile walloc_native.c as a shared library and load it."""
    src = "/app/walloc_native.c"
    out = "/app/libwalloc_native.so"
    assert os.path.exists(src), (
        f"Source file {src} does not exist. "
        "Create /app/walloc_native.c with the ported allocator."
    )
    result = subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O2", "-DNDEBUG",
         "-o", out, src],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"Compilation failed:\n{result.stderr}"
    )

    lib = ctypes.CDLL(out)
    lib.walloc_malloc.restype = ctypes.c_void_p
    lib.walloc_malloc.argtypes = [ctypes.c_size_t]
    lib.walloc_free.restype = None
    lib.walloc_free.argtypes = [ctypes.c_void_p]
    lib.walloc_realloc.restype = ctypes.c_void_p
    lib.walloc_realloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    lib.walloc_malloc_usable_size.restype = ctypes.c_size_t
    lib.walloc_malloc_usable_size.argtypes = [ctypes.c_void_p]
    return lib


# ── helpers ──────────────────────────────────────────────────────────────────

def _write_pattern(ptr, size, byte):
    """Fill *ptr* with *byte* for *size* bytes."""
    ctypes.memset(ptr, byte, size)


def _read_bytes(ptr, n):
    """Return the first *n* bytes at *ptr* as a bytes object."""
    return bytes((ctypes.c_ubyte * n).from_address(ptr))


# ── compilation & header ─────────────────────────────────────────────────────

class TestCompilation:
    def test_compiles_and_loads(self, lib):
        assert lib is not None

    def test_header_exists(self):
        assert os.path.exists("/app/walloc_native.h"), (
            "Missing /app/walloc_native.h with public API declarations."
        )


# ── basic malloc / free ──────────────────────────────────────────────────────

class TestBasicAllocation:
    @pytest.mark.parametrize("size", [
        1, 8, 9, 16, 17, 24, 25, 32, 33, 40, 41, 48,
        49, 64, 65, 80, 81, 128, 129, 256,
    ])
    def test_small_malloc(self, lib, size):
        ptr = lib.walloc_malloc(size)
        assert ptr and ptr != 0, f"walloc_malloc({size}) returned NULL"
        _write_pattern(ptr, size, 0xAA)
        lib.walloc_free(ptr)

    @pytest.mark.parametrize("size", [257, 512, 1024, 4096, 8192, 65536])
    def test_large_malloc(self, lib, size):
        ptr = lib.walloc_malloc(size)
        assert ptr and ptr != 0, f"walloc_malloc({size}) returned NULL"
        _write_pattern(ptr, size, 0xBB)
        lib.walloc_free(ptr)

    def test_zero_size(self, lib):
        ptr = lib.walloc_malloc(0)
        assert ptr and ptr != 0, "walloc_malloc(0) should return a valid pointer"
        lib.walloc_free(ptr)

    def test_many_same_class(self, lib):
        ptrs = []
        for _ in range(100):
            p = lib.walloc_malloc(16)
            assert p and p != 0
            ptrs.append(p)
        for p in ptrs:
            lib.walloc_free(p)


class TestFree:
    def test_free_null(self, lib):
        lib.walloc_free(None)  # must not crash

    def test_reuse_after_free(self, lib):
        p1 = lib.walloc_malloc(16)
        lib.walloc_free(p1)
        p2 = lib.walloc_malloc(16)
        assert p2 and p2 != 0
        lib.walloc_free(p2)


# ── malloc_usable_size ───────────────────────────────────────────────────────

class TestMallocUsableSize:
    """Verify usable size matches walloc's size-class granularity.

    Size classes (granules): 1 2 3 4 5 6 8 10 16 32  (granule = 8 bytes)
    """

    @pytest.mark.parametrize("req,expected", [
        (1, 8), (7, 8), (8, 8),
        (9, 16), (15, 16), (16, 16),
        (17, 24), (24, 24),
        (25, 32), (32, 32),
        (33, 40), (40, 40),
        (41, 48), (48, 48),
        (49, 64), (64, 64),
        (65, 80), (80, 80),
        (81, 128), (128, 128),
        (129, 256), (200, 256), (256, 256),
    ])
    def test_small_usable(self, lib, req, expected):
        ptr = lib.walloc_malloc(req)
        usable = lib.walloc_malloc_usable_size(ptr)
        assert usable == expected, (
            f"walloc_malloc_usable_size(walloc_malloc({req})) = {usable}, "
            f"expected {expected}"
        )
        lib.walloc_free(ptr)

    @pytest.mark.parametrize("size", [257, 300, 512, 1000, 4096, 32768])
    def test_large_usable_ge_requested(self, lib, size):
        ptr = lib.walloc_malloc(size)
        usable = lib.walloc_malloc_usable_size(ptr)
        assert usable >= size, (
            f"walloc_malloc_usable_size(walloc_malloc({size})) = {usable} < {size}"
        )
        lib.walloc_free(ptr)

    def test_null_returns_zero(self, lib):
        assert lib.walloc_malloc_usable_size(None) == 0


# ── realloc ──────────────────────────────────────────────────────────────────

class TestRealloc:
    def test_null_acts_as_malloc(self, lib):
        ptr = lib.walloc_realloc(None, 100)
        assert ptr and ptr != 0
        _write_pattern(ptr, 100, 0xCC)
        lib.walloc_free(ptr)

    def test_zero_acts_as_free(self, lib):
        ptr = lib.walloc_malloc(100)
        result = lib.walloc_realloc(ptr, 0)
        assert result is None or result == 0

    def test_same_small_class_identity(self, lib):
        """realloc within same size class must return the same pointer."""
        ptr = lib.walloc_malloc(10)       # 2 granules → 16 bytes
        _write_pattern(ptr, 10, 0xDD)
        new = lib.walloc_realloc(ptr, 15) # still 2 granules → 16 bytes
        assert new == ptr, (
            "realloc within same size class should return the same pointer"
        )
        assert _read_bytes(new, 10) == bytes([0xDD] * 10)
        lib.walloc_free(new)

    def test_grow_small_cross_class(self, lib):
        ptr = lib.walloc_malloc(10)
        pattern = bytes(range(10))
        ctypes.memmove(ptr, pattern, 10)
        new = lib.walloc_realloc(ptr, 100)
        assert new and new != 0
        assert _read_bytes(new, 10) == pattern
        lib.walloc_free(new)

    def test_shrink_small_cross_class(self, lib):
        ptr = lib.walloc_malloc(100)
        pattern = bytes(range(10))
        ctypes.memmove(ptr, pattern, 10)
        new = lib.walloc_realloc(ptr, 10)
        assert new and new != 0
        assert _read_bytes(new, 10) == pattern
        lib.walloc_free(new)

    def test_small_to_large(self, lib):
        ptr = lib.walloc_malloc(32)
        pattern = bytes(range(32))
        ctypes.memmove(ptr, pattern, 32)
        new = lib.walloc_realloc(ptr, 1000)
        assert new and new != 0
        assert _read_bytes(new, 32) == pattern
        lib.walloc_free(new)

    def test_large_to_small(self, lib):
        ptr = lib.walloc_malloc(1000)
        pattern = bytes(range(32))
        ctypes.memmove(ptr, pattern, 32)
        new = lib.walloc_realloc(ptr, 32)
        assert new and new != 0
        assert _read_bytes(new, 32) == pattern
        lib.walloc_free(new)

    def test_large_grow(self, lib):
        ptr = lib.walloc_malloc(500)
        pattern = b"\xEE" * 200
        ctypes.memmove(ptr, pattern, 200)
        new = lib.walloc_realloc(ptr, 2000)
        assert new and new != 0
        assert _read_bytes(new, 200) == pattern
        lib.walloc_free(new)

    def test_large_shrink(self, lib):
        ptr = lib.walloc_malloc(2000)
        pattern = b"\xFF" * 300
        ctypes.memmove(ptr, pattern, 300)
        new = lib.walloc_realloc(ptr, 300)
        assert new and new != 0
        assert _read_bytes(new, 300) == pattern
        lib.walloc_free(new)

    def test_realloc_preserves_across_boundary(self, lib):
        """Allocate near the small/large boundary, realloc across it."""
        ptr = lib.walloc_malloc(250)       # 32 granules → 256 bytes (small)
        pattern = b"\xAB" * 250
        ctypes.memmove(ptr, pattern, 250)
        new = lib.walloc_realloc(ptr, 300) # large object
        assert new and new != 0
        assert _read_bytes(new, 250) == pattern
        lib.walloc_free(new)


# ── stress tests ─────────────────────────────────────────────────────────────

class TestStress:
    def test_alloc_free_cycles(self, lib):
        rng = random.Random(42)
        ptrs = {}
        for i in range(5000):
            if ptrs and rng.random() < 0.4:
                addr = rng.choice(list(ptrs.keys()))
                lib.walloc_free(addr)
                del ptrs[addr]
            else:
                size = rng.randint(1, 4096)
                ptr = lib.walloc_malloc(size)
                assert ptr and ptr != 0, (
                    f"walloc_malloc({size}) returned NULL at iteration {i}"
                )
                _write_pattern(ptr, min(size, 8), i & 0xFF)
                ptrs[ptr] = size
        for addr in list(ptrs):
            lib.walloc_free(addr)

    def test_realloc_stress(self, lib):
        rng = random.Random(123)
        ptrs = []
        for i in range(1000):
            if ptrs and rng.random() < 0.5:
                idx = rng.randint(0, len(ptrs) - 1)
                ptr, _ = ptrs[idx]
                new_size = rng.randint(1, 4096)
                new_ptr = lib.walloc_realloc(ptr, new_size)
                assert new_ptr and new_ptr != 0
                ptrs[idx] = (new_ptr, new_size)
            else:
                size = rng.randint(1, 4096)
                ptr = lib.walloc_malloc(size)
                assert ptr and ptr != 0
                ptrs.append((ptr, size))
        for ptr, _ in ptrs:
            lib.walloc_free(ptr)

    def test_data_integrity(self, lib):
        """Allocate many objects, write patterns, verify all survive."""
        rng = random.Random(456)
        allocs = []
        for i in range(200):
            size = rng.randint(1, 2048)
            ptr = lib.walloc_malloc(size)
            assert ptr and ptr != 0
            byte = i & 0xFF
            _write_pattern(ptr, size, byte)
            allocs.append((ptr, size, byte))

        for ptr, size, byte in allocs:
            data = _read_bytes(ptr, size)
            for j, b in enumerate(data):
                assert b == byte, (
                    f"Corruption at alloc {allocs.index((ptr,size,byte))}, "
                    f"offset {j}: expected 0x{byte:02x}, got 0x{b:02x}"
                )

        for ptr, _, _ in allocs:
            lib.walloc_free(ptr)

    def test_many_pages(self, lib):
        """Allocate enough to span many 64KB pages."""
        ptrs = []
        total = 0
        target = 2 * 1024 * 1024  # 2 MB
        while total < target:
            size = 4096
            ptr = lib.walloc_malloc(size)
            assert ptr and ptr != 0
            _write_pattern(ptr, size, 0x42)
            ptrs.append(ptr)
            total += size
        for ptr in ptrs:
            lib.walloc_free(ptr)


# ── alignment ────────────────────────────────────────────────────────────────

class TestAlignment:
    def test_small_8byte_aligned(self, lib):
        """All small allocations must be at least 8-byte aligned."""
        for size in [1, 8, 16, 24, 32, 48, 64, 80, 128, 256]:
            ptr = lib.walloc_malloc(size)
            assert ptr % 8 == 0, (
                f"walloc_malloc({size}) returned non-8-byte-aligned ptr 0x{ptr:x}"
            )
            lib.walloc_free(ptr)

    def test_large_chunk_aligned(self, lib):
        """Large-object payloads start at header_size offset from chunk boundary."""
        for size in [257, 1024, 8192]:
            ptr = lib.walloc_malloc(size)
            assert ptr % 8 == 0, (
                f"walloc_malloc({size}) returned non-8-byte-aligned ptr 0x{ptr:x}"
            )
            lib.walloc_free(ptr)
