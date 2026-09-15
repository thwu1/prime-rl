
import ctypes
import os
import subprocess
import pytest
import random


class WallocStats(ctypes.Structure):
    """Matches walloc_stats_t from walloc_native.h"""
    _fields_ = [
        ("heap_pages", ctypes.c_size_t),
        ("large_obj_count", ctypes.c_size_t),
        ("large_obj_bytes", ctypes.c_size_t),
        ("small_obj_count", ctypes.c_size_t),
        ("free_large_bytes", ctypes.c_size_t),
        ("free_small_count", ctypes.c_size_t),
    ]


@pytest.fixture(scope="session")
def lib():
    """Load the compiled shared library."""
    so_path = "/app/libwalloc.so"
    assert os.path.exists(so_path), f"Shared library not found: {so_path}"

    lib = ctypes.CDLL(so_path)

    # walloc_init / walloc_destroy
    lib.walloc_init.argtypes = [ctypes.c_size_t]
    lib.walloc_init.restype = None
    lib.walloc_destroy.argtypes = []
    lib.walloc_destroy.restype = None

    # walloc_malloc / walloc_free
    lib.walloc_malloc.argtypes = [ctypes.c_size_t]
    lib.walloc_malloc.restype = ctypes.c_void_p
    lib.walloc_free.argtypes = [ctypes.c_void_p]
    lib.walloc_free.restype = None

    # walloc_realloc / walloc_calloc
    lib.walloc_realloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    lib.walloc_realloc.restype = ctypes.c_void_p
    lib.walloc_calloc.argtypes = [ctypes.c_size_t, ctypes.c_size_t]
    lib.walloc_calloc.restype = ctypes.c_void_p

    # walloc_get_stats / walloc_validate_heap
    lib.walloc_get_stats.argtypes = [ctypes.POINTER(WallocStats)]
    lib.walloc_get_stats.restype = None
    lib.walloc_validate_heap.argtypes = []
    lib.walloc_validate_heap.restype = ctypes.c_int

    return lib


@pytest.fixture(autouse=True)
def heap(lib):
    """Initialize and destroy the heap for each test."""
    lib.walloc_init(64 * 1024 * 1024)  # 64 MB
    yield lib
    lib.walloc_destroy()


def get_stats(lib):
    stats = WallocStats()
    lib.walloc_get_stats(ctypes.byref(stats))
    return stats


# ---------------------------------------------------------------------------
# Basic malloc / free
# ---------------------------------------------------------------------------

class TestBasicMalloc:
    def test_small_allocation(self, heap):
        ptr = heap.walloc_malloc(8)
        assert ptr is not None and ptr != 0
        heap.walloc_free(ptr)

    def test_medium_allocation(self, heap):
        ptr = heap.walloc_malloc(100)
        assert ptr is not None and ptr != 0
        heap.walloc_free(ptr)

    def test_large_allocation(self, heap):
        ptr = heap.walloc_malloc(1024)
        assert ptr is not None and ptr != 0
        heap.walloc_free(ptr)

    def test_very_large_allocation(self, heap):
        ptr = heap.walloc_malloc(100_000)
        assert ptr is not None and ptr != 0
        heap.walloc_free(ptr)

    def test_free_null(self, heap):
        heap.walloc_free(None)  # must not crash

    def test_multiple_allocations(self, heap):
        ptrs = []
        for _ in range(100):
            p = heap.walloc_malloc(64)
            assert p is not None and p != 0
            ptrs.append(p)
        for p in ptrs:
            heap.walloc_free(p)

    def test_write_and_read(self, heap):
        """Verify allocated memory is writable and readable."""
        ptr = heap.walloc_malloc(256)
        assert ptr is not None and ptr != 0
        pattern = b"ABCD" * 64  # 256 bytes
        ctypes.memmove(ptr, pattern, 256)
        buf = ctypes.create_string_buffer(256)
        ctypes.memmove(buf, ptr, 256)
        assert buf.raw == pattern
        heap.walloc_free(ptr)

    def test_alignment(self, heap):
        """All allocations should be at least 8-byte aligned."""
        for size in [1, 2, 3, 7, 8, 9, 15, 16, 32, 48, 64, 100, 256, 512, 1024]:
            ptr = heap.walloc_malloc(size)
            assert ptr is not None and ptr != 0
            assert ptr % 8 == 0, f"Alloc of {size} bytes not 8-byte aligned: {ptr:#x}"
            heap.walloc_free(ptr)

    def test_distinct_pointers(self, heap):
        """Concurrent allocations must return distinct pointers."""
        a = heap.walloc_malloc(32)
        b = heap.walloc_malloc(32)
        assert a != b
        heap.walloc_free(a)
        heap.walloc_free(b)


# ---------------------------------------------------------------------------
# Size classes
# ---------------------------------------------------------------------------

class TestSizeClasses:
    """Test allocation at each size class boundary.

    walloc size classes: 1,2,3,4,5,6,8,10,16,32 granules (granule=8 bytes)
    So usable bytes per class: 8,16,24,32,40,48,64,80,128,256
    """

    @pytest.mark.parametrize("alloc_size,class_bytes", [
        (1, 8),
        (8, 8),
        (9, 16),
        (16, 16),
        (17, 24),
        (24, 24),
        (25, 32),
        (32, 32),
        (33, 40),
        (40, 40),
        (41, 48),
        (48, 48),
        (49, 64),
        (64, 64),
        (65, 80),
        (80, 80),
        (81, 128),
        (128, 128),
        (129, 256),
        (256, 256),
    ])
    def test_size_class(self, heap, alloc_size, class_bytes):
        ptr = heap.walloc_malloc(alloc_size)
        assert ptr is not None and ptr != 0
        # Write and read back full class-size to verify it is usable
        pattern = bytes([alloc_size & 0xFF]) * class_bytes
        ctypes.memmove(ptr, pattern, class_bytes)
        buf = ctypes.create_string_buffer(class_bytes)
        ctypes.memmove(buf, ptr, class_bytes)
        assert buf.raw == pattern
        heap.walloc_free(ptr)

    def test_large_object_boundary(self, heap):
        """257 bytes should be a large object (>256 = >32 granules)."""
        ptr = heap.walloc_malloc(257)
        assert ptr is not None and ptr != 0
        pattern = b"X" * 257
        ctypes.memmove(ptr, pattern, 257)
        buf = ctypes.create_string_buffer(257)
        ctypes.memmove(buf, ptr, 257)
        assert buf.raw == pattern
        heap.walloc_free(ptr)


# ---------------------------------------------------------------------------
# realloc
# ---------------------------------------------------------------------------

class TestRealloc:
    def test_realloc_null(self, heap):
        """realloc(NULL, size) should behave like malloc(size)."""
        ptr = heap.walloc_realloc(None, 100)
        assert ptr is not None and ptr != 0
        heap.walloc_free(ptr)

    def test_realloc_zero(self, heap):
        """realloc(ptr, 0) should free and return NULL."""
        ptr = heap.walloc_malloc(100)
        result = heap.walloc_realloc(ptr, 0)
        assert result is None or result == 0

    def test_realloc_grow_small(self, heap):
        """Grow a small allocation; data must be preserved."""
        ptr = heap.walloc_malloc(16)
        ctypes.memmove(ptr, b"Hello, World!!!!", 16)
        new_ptr = heap.walloc_realloc(ptr, 100)
        assert new_ptr is not None and new_ptr != 0
        buf = ctypes.create_string_buffer(16)
        ctypes.memmove(buf, new_ptr, 16)
        assert buf.raw == b"Hello, World!!!!"
        heap.walloc_free(new_ptr)

    def test_realloc_grow_large(self, heap):
        """Grow a large allocation; data must be preserved."""
        ptr = heap.walloc_malloc(512)
        pattern = b"Y" * 512
        ctypes.memmove(ptr, pattern, 512)
        new_ptr = heap.walloc_realloc(ptr, 2048)
        assert new_ptr is not None and new_ptr != 0
        buf = ctypes.create_string_buffer(512)
        ctypes.memmove(buf, new_ptr, 512)
        assert buf.raw == pattern
        heap.walloc_free(new_ptr)

    def test_realloc_shrink(self, heap):
        """Shrink an allocation; data prefix must be preserved."""
        ptr = heap.walloc_malloc(1024)
        pattern = b"Z" * 64
        ctypes.memmove(ptr, pattern, 64)
        new_ptr = heap.walloc_realloc(ptr, 64)
        assert new_ptr is not None and new_ptr != 0
        buf = ctypes.create_string_buffer(64)
        ctypes.memmove(buf, new_ptr, 64)
        assert buf.raw == pattern
        heap.walloc_free(new_ptr)

    def test_realloc_same_small_class(self, heap):
        """Realloc within same small size class should return same pointer."""
        ptr = heap.walloc_malloc(10)  # 2 granules -> 16 bytes
        new_ptr = heap.walloc_realloc(ptr, 15)  # still 2 granules
        assert new_ptr == ptr
        heap.walloc_free(new_ptr)

    def test_realloc_small_to_large(self, heap):
        """Realloc from small to large object; data preserved."""
        ptr = heap.walloc_malloc(32)
        ctypes.memmove(ptr, b"A" * 32, 32)
        new_ptr = heap.walloc_realloc(ptr, 1024)
        assert new_ptr is not None and new_ptr != 0
        buf = ctypes.create_string_buffer(32)
        ctypes.memmove(buf, new_ptr, 32)
        assert buf.raw == b"A" * 32
        heap.walloc_free(new_ptr)

    def test_realloc_large_to_small(self, heap):
        """Realloc from large to small; data prefix preserved."""
        ptr = heap.walloc_malloc(1024)
        ctypes.memmove(ptr, b"B" * 32, 32)
        new_ptr = heap.walloc_realloc(ptr, 32)
        assert new_ptr is not None and new_ptr != 0
        buf = ctypes.create_string_buffer(32)
        ctypes.memmove(buf, new_ptr, 32)
        assert buf.raw == b"B" * 32
        heap.walloc_free(new_ptr)

    def test_realloc_preserves_data_across_classes(self, heap):
        """Realloc across different small size classes preserves data."""
        ptr = heap.walloc_malloc(8)  # 1 granule
        ctypes.memmove(ptr, b"\xDE\xAD\xBE\xEF\xCA\xFE\xBA\xBE", 8)
        new_ptr = heap.walloc_realloc(ptr, 64)  # 8 granules
        assert new_ptr is not None and new_ptr != 0
        buf = ctypes.create_string_buffer(8)
        ctypes.memmove(buf, new_ptr, 8)
        assert buf.raw == b"\xDE\xAD\xBE\xEF\xCA\xFE\xBA\xBE"
        heap.walloc_free(new_ptr)


# ---------------------------------------------------------------------------
# calloc
# ---------------------------------------------------------------------------

class TestCalloc:
    def test_calloc_zeroes_small(self, heap):
        ptr = heap.walloc_calloc(1, 8)
        assert ptr is not None and ptr != 0
        buf = ctypes.create_string_buffer(8)
        ctypes.memmove(buf, ptr, 8)
        assert buf.raw == b"\x00" * 8
        heap.walloc_free(ptr)

    def test_calloc_zeroes_medium(self, heap):
        ptr = heap.walloc_calloc(10, 100)
        assert ptr is not None and ptr != 0
        buf = ctypes.create_string_buffer(1000)
        ctypes.memmove(buf, ptr, 1000)
        assert buf.raw == b"\x00" * 1000
        heap.walloc_free(ptr)

    def test_calloc_zeroes_large(self, heap):
        ptr = heap.walloc_calloc(1, 4096)
        assert ptr is not None and ptr != 0
        buf = ctypes.create_string_buffer(4096)
        ctypes.memmove(buf, ptr, 4096)
        assert buf.raw == b"\x00" * 4096
        heap.walloc_free(ptr)

    def test_calloc_after_dirty(self, heap):
        """calloc should zero even when reusing freed memory."""
        p = heap.walloc_malloc(64)
        ctypes.memset(p, 0xFF, 64)
        heap.walloc_free(p)
        p2 = heap.walloc_calloc(1, 64)
        assert p2 is not None and p2 != 0
        buf = ctypes.create_string_buffer(64)
        ctypes.memmove(buf, p2, 64)
        assert buf.raw == b"\x00" * 64
        heap.walloc_free(p2)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class TestStats:
    def test_initial_stats(self, heap):
        stats = get_stats(heap)
        assert stats.large_obj_count == 0
        assert stats.small_obj_count == 0

    def test_stats_after_large_allocs(self, heap):
        ptrs = [heap.walloc_malloc(1024) for _ in range(5)]
        stats = get_stats(heap)
        assert stats.large_obj_count == 5
        assert stats.large_obj_bytes >= 5 * 1024
        for p in ptrs:
            heap.walloc_free(p)

    def test_stats_after_small_allocs(self, heap):
        ptrs = [heap.walloc_malloc(32) for _ in range(20)]
        stats = get_stats(heap)
        assert stats.small_obj_count == 20
        for p in ptrs:
            heap.walloc_free(p)

    def test_stats_after_free(self, heap):
        ptrs = [heap.walloc_malloc(1024) for _ in range(10)]
        for p in ptrs[:5]:
            heap.walloc_free(p)
        stats = get_stats(heap)
        assert stats.large_obj_count == 5
        assert stats.free_large_bytes > 0
        for p in ptrs[5:]:
            heap.walloc_free(p)

    def test_stats_heap_pages(self, heap):
        heap.walloc_malloc(8)
        stats = get_stats(heap)
        assert stats.heap_pages >= 1

    def test_stats_free_small(self, heap):
        ptrs = [heap.walloc_malloc(16) for _ in range(10)]
        for p in ptrs:
            heap.walloc_free(p)
        stats = get_stats(heap)
        assert stats.small_obj_count == 0
        assert stats.free_small_count >= 10

    def test_stats_mixed(self, heap):
        small = [heap.walloc_malloc(24) for _ in range(15)]
        large = [heap.walloc_malloc(512) for _ in range(3)]
        stats = get_stats(heap)
        assert stats.small_obj_count == 15
        assert stats.large_obj_count == 3
        for p in small:
            heap.walloc_free(p)
        for p in large:
            heap.walloc_free(p)


# ---------------------------------------------------------------------------
# Validate heap
# ---------------------------------------------------------------------------

class TestValidateHeap:
    def test_validate_empty(self, heap):
        assert heap.walloc_validate_heap() == 1

    def test_validate_after_allocs(self, heap):
        ptrs = [heap.walloc_malloc(s)
                for s in [8, 16, 32, 64, 128, 256, 512, 1024]]
        assert heap.walloc_validate_heap() == 1
        for p in ptrs:
            heap.walloc_free(p)

    def test_validate_after_free(self, heap):
        ptrs = [heap.walloc_malloc(100) for _ in range(50)]
        for p in ptrs[:25]:
            heap.walloc_free(p)
        assert heap.walloc_validate_heap() == 1
        for p in ptrs[25:]:
            heap.walloc_free(p)
        assert heap.walloc_validate_heap() == 1

    def test_validate_after_realloc(self, heap):
        ptrs = [heap.walloc_malloc(64) for _ in range(20)]
        ptrs = [heap.walloc_realloc(p, 256) for p in ptrs]
        assert heap.walloc_validate_heap() == 1
        for p in ptrs:
            heap.walloc_free(p)
        assert heap.walloc_validate_heap() == 1

    def test_validate_after_mixed_sizes(self, heap):
        random.seed(123)
        ptrs = []
        for _ in range(100):
            s = random.choice([1, 8, 16, 24, 48, 64, 128, 256, 300, 1024, 4096])
            ptrs.append(heap.walloc_malloc(s))
        random.shuffle(ptrs)
        for p in ptrs[:50]:
            heap.walloc_free(p)
        assert heap.walloc_validate_heap() == 1
        for p in ptrs[50:]:
            heap.walloc_free(p)
        assert heap.walloc_validate_heap() == 1


# ---------------------------------------------------------------------------
# Stress
# ---------------------------------------------------------------------------

class TestStress:
    def test_random_operations(self, heap):
        """Run 1000 random malloc/free/realloc operations."""
        random.seed(42)
        ptrs = []
        for _ in range(1000):
            op = random.random()
            if op < 0.4 or not ptrs:
                size = random.randint(1, 4096)
                p = heap.walloc_malloc(size)
                assert p is not None and p != 0
                # Write a byte to verify accessibility
                ctypes.memset(p, 0xAA, min(size, 1))
                ptrs.append((p, size))
            elif op < 0.7:
                idx = random.randint(0, len(ptrs) - 1)
                p, _ = ptrs.pop(idx)
                heap.walloc_free(p)
            else:
                idx = random.randint(0, len(ptrs) - 1)
                p, old_size = ptrs[idx]
                new_size = random.randint(1, 4096)
                new_p = heap.walloc_realloc(p, new_size)
                assert new_p is not None and new_p != 0
                ptrs[idx] = (new_p, new_size)

        assert heap.walloc_validate_heap() == 1

        for p, _ in ptrs:
            heap.walloc_free(p)

    def test_many_small_allocations(self, heap):
        """Allocate 5000 small objects across various size classes."""
        random.seed(99)
        ptrs = []
        for _ in range(5000):
            size = random.choice([8, 16, 24, 32, 40, 48, 64, 80, 128, 256])
            p = heap.walloc_malloc(size)
            assert p is not None and p != 0
            ptrs.append(p)

        assert heap.walloc_validate_heap() == 1

        for p in ptrs:
            heap.walloc_free(p)

    def test_large_object_churn(self, heap):
        """Allocate and free large objects to exercise coalescing."""
        for _ in range(100):
            ptrs = [heap.walloc_malloc(random.randint(300, 8000))
                    for _ in range(10)]
            random.shuffle(ptrs)
            for p in ptrs:
                heap.walloc_free(p)
        assert heap.walloc_validate_heap() == 1
