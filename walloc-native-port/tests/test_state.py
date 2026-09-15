
import ctypes
import subprocess
import os
import pytest
import random

LIB_PATH = "/tmp/libwalloc_test.so"


class WallocStats(ctypes.Structure):
    _fields_ = [
        ("total_allocated_bytes", ctypes.c_size_t),
        ("total_freed_bytes", ctypes.c_size_t),
        ("current_live_bytes", ctypes.c_size_t),
        ("peak_live_bytes", ctypes.c_size_t),
        ("num_pages", ctypes.c_size_t),
        ("fragmentation_ratio", ctypes.c_double),
    ]


@pytest.fixture(scope="session")
def compile_lib():
    """Compile walloc_native.c as a shared library."""
    assert os.path.exists("/app/walloc_native.c"), "walloc_native.c not found in /app/"
    assert os.path.exists("/app/walloc_native.h"), "walloc_native.h not found in /app/"
    result = subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O2", "-DNDEBUG",
         "-I/app", "-o", LIB_PATH, "/app/walloc_native.c"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"Compilation failed:\n{result.stderr}"
    return LIB_PATH


def _load_lib(lib_path):
    """Load the shared library and set up function signatures."""
    lib = ctypes.CDLL(lib_path)
    lib.walloc_init.restype = None
    lib.walloc_init.argtypes = []
    lib.walloc_destroy.restype = None
    lib.walloc_destroy.argtypes = []
    lib.walloc_malloc.restype = ctypes.c_void_p
    lib.walloc_malloc.argtypes = [ctypes.c_size_t]
    lib.walloc_free.restype = None
    lib.walloc_free.argtypes = [ctypes.c_void_p]
    lib.walloc_realloc.restype = ctypes.c_void_p
    lib.walloc_realloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    lib.walloc_calloc.restype = ctypes.c_void_p
    lib.walloc_calloc.argtypes = [ctypes.c_size_t, ctypes.c_size_t]
    lib.walloc_get_stats.restype = None
    lib.walloc_get_stats.argtypes = [ctypes.POINTER(WallocStats)]
    return lib


@pytest.fixture
def w(compile_lib):
    """Provide an initialized walloc instance, destroyed after each test."""
    lib = _load_lib(compile_lib)
    lib.walloc_init()
    yield lib
    lib.walloc_destroy()


def _get_stats(lib):
    stats = WallocStats()
    lib.walloc_get_stats(ctypes.byref(stats))
    return stats


# ---------- Tests ----------


def test_compilation(compile_lib):
    """The library compiles successfully."""
    assert os.path.exists(compile_lib)


def test_small_allocations(w):
    """Allocate various small sizes, write data, verify, free."""
    sizes = [1, 7, 8, 16, 24, 32, 48, 64, 80, 128, 200, 256]
    ptrs = []
    for size in sizes:
        p = w.walloc_malloc(size)
        assert p is not None and p != 0, f"malloc({size}) returned NULL"
        assert p % 8 == 0, f"malloc({size}) returned unaligned pointer {p:#x}"
        pattern = (ctypes.c_ubyte * size)(*[i & 0xFF for i in range(size)])
        ctypes.memmove(p, pattern, size)
        ptrs.append((p, size))

    # Verify data integrity
    for p, size in ptrs:
        buf = (ctypes.c_ubyte * size).from_address(p)
        for i in range(size):
            assert buf[i] == (i & 0xFF), \
                f"Data mismatch at offset {i} for size {size}"

    for p, _ in ptrs:
        w.walloc_free(p)


def test_large_allocations(w):
    """Allocate various large sizes, write data, verify, free."""
    sizes = [257, 512, 1024, 2048, 4096, 8192, 16384]
    ptrs = []
    for size in sizes:
        p = w.walloc_malloc(size)
        assert p is not None and p != 0, f"malloc({size}) returned NULL"
        assert p % 8 == 0, f"malloc({size}) returned unaligned pointer {p:#x}"
        ctypes.memset(p, 0xDE, size)
        ptrs.append((p, size))

    for p, size in ptrs:
        buf = (ctypes.c_ubyte * size).from_address(p)
        assert all(b == 0xDE for b in buf), f"Data corrupted for size {size}"

    for p, _ in ptrs:
        w.walloc_free(p)


def test_realloc_null_and_zero(w):
    """realloc(NULL, n) works like malloc; realloc(p, 0) works like free."""
    # realloc(NULL, size) => malloc
    p = w.walloc_realloc(None, 100)
    assert p is not None and p != 0, "realloc(NULL, 100) returned NULL"
    ctypes.memset(p, 0xAB, 100)

    # realloc(ptr, 0) => free, returns NULL
    q = w.walloc_realloc(p, 0)
    assert q is None or q == 0, "realloc(ptr, 0) should return NULL"


def test_realloc_same_size_class(w):
    """realloc within same small-object size class returns same pointer."""
    # Sizes 5 and 7 both fit in 1 granule (8 bytes) = GRANULES_1
    p = w.walloc_malloc(5)
    assert p is not None and p != 0
    ctypes.memset(p, 0xCC, 5)

    q = w.walloc_realloc(p, 7)
    assert q == p, \
        f"realloc within same size class should return same pointer (got {q:#x} != {p:#x})"
    buf = (ctypes.c_ubyte * 5).from_address(q)
    assert all(b == 0xCC for b in buf), "Data not preserved in same-class realloc"
    w.walloc_free(q)


def test_realloc_grow_small(w):
    """realloc small object to larger size (different class) preserves data."""
    p = w.walloc_malloc(32)
    assert p is not None and p != 0
    data = bytes(range(32))
    ctypes.memmove(p, data, 32)

    q = w.walloc_realloc(p, 128)
    assert q is not None and q != 0
    buf = (ctypes.c_ubyte * 32).from_address(q)
    assert bytes(buf) == data, "Data not preserved after small-object grow"
    w.walloc_free(q)


def test_realloc_shrink(w):
    """realloc to smaller size preserves prefix data."""
    p = w.walloc_malloc(128)
    assert p is not None and p != 0
    data = bytes(range(128))
    ctypes.memmove(p, data, 128)

    q = w.walloc_realloc(p, 32)
    assert q is not None and q != 0
    buf = (ctypes.c_ubyte * 32).from_address(q)
    assert bytes(buf) == data[:32], "Data not preserved after shrink"
    w.walloc_free(q)


def test_realloc_small_to_large(w):
    """realloc from small object to large object preserves data."""
    p = w.walloc_malloc(64)
    assert p is not None and p != 0
    data = bytes([0x42] * 64)
    ctypes.memmove(p, data, 64)

    q = w.walloc_realloc(p, 512)
    assert q is not None and q != 0
    buf = (ctypes.c_ubyte * 64).from_address(q)
    assert bytes(buf) == data, "Data not preserved in small-to-large realloc"
    w.walloc_free(q)


def test_realloc_large_to_small(w):
    """realloc from large object to small object preserves prefix data."""
    p = w.walloc_malloc(512)
    assert p is not None and p != 0
    data = bytes([0x37] * 64)
    ctypes.memmove(p, data, 64)

    q = w.walloc_realloc(p, 64)
    assert q is not None and q != 0
    buf = (ctypes.c_ubyte * 64).from_address(q)
    assert bytes(buf) == data, "Data not preserved in large-to-small realloc"
    w.walloc_free(q)


def test_realloc_large_inplace_growth(w):
    """Large object realloc should grow in place when adjacent space is free."""
    # Allocate 300 bytes (large object, will use ~2 chunks from a fresh page)
    p = w.walloc_malloc(300)
    assert p is not None and p != 0
    data = bytes([i & 0xFF for i in range(300)])
    ctypes.memmove(p, data, 300)

    # Grow to 600 — adjacent free space in same page should allow in-place growth
    q = w.walloc_realloc(p, 600)
    assert q is not None and q != 0
    assert q == p, \
        f"realloc should grow large object in place when adjacent space is free " \
        f"(got {q:#x} != {p:#x})"
    buf = (ctypes.c_ubyte * 300).from_address(q)
    assert bytes(buf) == data, "Data not preserved after in-place growth"
    w.walloc_free(q)


def test_calloc_zeroed(w):
    """calloc returns zeroed memory."""
    p = w.walloc_calloc(10, 100)
    assert p is not None and p != 0
    buf = (ctypes.c_ubyte * 1000).from_address(p)
    assert all(b == 0 for b in buf), "calloc memory not zeroed"
    w.walloc_free(p)


def test_stats_consistency(w):
    """Statistics are internally consistent throughout alloc/free cycle."""
    s0 = _get_stats(w)
    assert s0.current_live_bytes == 0, "Initial current_live should be 0"
    assert s0.total_allocated_bytes == 0, "Initial total_allocated should be 0"

    ptrs = []
    for _ in range(10):
        p = w.walloc_malloc(100)
        assert p is not None and p != 0
        ptrs.append(p)

    s1 = _get_stats(w)
    assert s1.current_live_bytes > 0, "current_live should increase after mallocs"
    assert s1.total_allocated_bytes > 0, "total_allocated should increase"
    assert s1.total_allocated_bytes == s1.current_live_bytes, \
        "With no frees, total_alloc should equal current_live"
    assert s1.peak_live_bytes >= s1.current_live_bytes, \
        "peak should be >= current"
    assert s1.num_pages >= 1, "Should have at least 1 page"

    # Free half
    for p in ptrs[:5]:
        w.walloc_free(p)

    s2 = _get_stats(w)
    assert s2.current_live_bytes < s1.current_live_bytes, \
        "current_live should decrease after frees"
    assert s2.total_freed_bytes > 0, "total_freed should increase"
    assert s2.total_allocated_bytes == s1.total_allocated_bytes, \
        "total_allocated shouldn't change without new allocs"
    assert s2.current_live_bytes == s2.total_allocated_bytes - s2.total_freed_bytes, \
        "current_live should equal total_alloc - total_freed"
    assert s2.peak_live_bytes == s1.peak_live_bytes, \
        "peak should not decrease"
    assert 0.0 <= s2.fragmentation_ratio <= 1.0, \
        "fragmentation_ratio should be in [0, 1]"

    # Free rest
    for p in ptrs[5:]:
        w.walloc_free(p)

    s3 = _get_stats(w)
    assert s3.current_live_bytes == 0, \
        "current_live should be 0 after freeing everything"


def test_stress(w):
    """Random alloc/free/realloc pattern without crashes, stats consistent."""
    rng = random.Random(42)
    live = []

    for _ in range(1000):
        action = rng.random()
        if action < 0.5 or len(live) == 0:
            # malloc
            size = rng.randint(1, 4096)
            p = w.walloc_malloc(size)
            assert p is not None and p != 0, f"malloc({size}) returned NULL"
            ctypes.memset(p, 0xBB, min(size, 256))
            live.append((p, size))
        elif action < 0.8:
            # free
            idx = rng.randint(0, len(live) - 1)
            p, _ = live.pop(idx)
            w.walloc_free(p)
        else:
            # realloc
            idx = rng.randint(0, len(live) - 1)
            p, old_size = live[idx]
            new_size = rng.randint(1, 4096)
            q = w.walloc_realloc(p, new_size)
            assert q is not None and q != 0, \
                f"realloc({p:#x}, {new_size}) returned NULL"
            live[idx] = (q, new_size)

    # Free remaining
    for p, _ in live:
        w.walloc_free(p)

    s = _get_stats(w)
    assert s.current_live_bytes == 0, \
        f"current_live should be 0 after freeing all, got {s.current_live_bytes}"
