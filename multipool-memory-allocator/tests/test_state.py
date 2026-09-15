"""
Tests for the memory pool allocator.

Builds /app via Meson, then exercises every public API through Python
ctypes, verifies symbol visibility via nm, and checks Valgrind cleanliness.
"""

import ctypes as ct
import subprocess
import os
import random
import pytest

REGION_SIZE = 1024 * 1024  # 1 MB

EXPECTED_SYMBOLS = {
    "pool_create", "pool_destroy", "pool_malloc", "pool_free",
    "pool_calloc", "pool_realloc", "pool_aligned_malloc",
    "pool_aligned_free", "pool_get_stats", "pool_set_lock",
}


# ── ctypes mirror of pool_stats_t ────────────────────────────────────

class PoolStats(ct.Structure):
    _fields_ = [
        ("total_size", ct.c_size_t),
        ("used_size", ct.c_size_t),
        ("free_size", ct.c_size_t),
        ("num_allocations", ct.c_size_t),
        ("num_frees", ct.c_size_t),
        ("largest_free_block", ct.c_size_t),
        ("num_free_blocks", ct.c_size_t),
        ("fragmentation", ct.c_double),
    ]


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def built():
    """Build the allocator with Meson and return the path to liballocator.so."""
    builddir = "/app/builddir"

    # Run meson setup
    if not os.path.isdir(builddir):
        r = subprocess.run(["meson", "setup", "builddir"], cwd="/app",
                           capture_output=True, text=True)
        if r.returncode != 0:
            pytest.fail(f"meson setup failed:\n{r.stdout}\n{r.stderr}")
    else:
        subprocess.run(["meson", "setup", "--reconfigure", "builddir"],
                       cwd="/app", capture_output=True, text=True)

    # Run ninja
    r = subprocess.run(["ninja", "-C", builddir],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.fail(f"ninja build failed:\n{r.stdout}\n{r.stderr}")

    # Locate the built library
    candidates = [
        os.path.join(builddir, "liballocator.so"),
        "/app/liballocator.so",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path

    # Broader search
    r = subprocess.run(["find", "/app", "-name", "liballocator.so", "-type", "f"],
                       capture_output=True, text=True)
    for p in r.stdout.strip().split("\n"):
        if p and os.path.exists(p):
            return p

    pytest.fail("liballocator.so not found after build")


@pytest.fixture(scope="session")
def lib(built):
    """Load the built shared library and configure ctypes signatures."""
    lib = ct.CDLL(built)

    # pool lifecycle
    lib.pool_create.argtypes = [ct.c_void_p, ct.c_size_t]
    lib.pool_create.restype = ct.c_void_p
    lib.pool_destroy.argtypes = [ct.c_void_p]
    lib.pool_destroy.restype = None

    # basic allocation
    lib.pool_malloc.argtypes = [ct.c_void_p, ct.c_size_t]
    lib.pool_malloc.restype = ct.c_void_p
    lib.pool_free.argtypes = [ct.c_void_p, ct.c_void_p]
    lib.pool_free.restype = None
    lib.pool_calloc.argtypes = [ct.c_void_p, ct.c_size_t, ct.c_size_t]
    lib.pool_calloc.restype = ct.c_void_p
    lib.pool_realloc.argtypes = [ct.c_void_p, ct.c_void_p, ct.c_size_t]
    lib.pool_realloc.restype = ct.c_void_p

    # aligned allocation
    lib.pool_aligned_malloc.argtypes = [ct.c_void_p, ct.c_size_t, ct.c_size_t]
    lib.pool_aligned_malloc.restype = ct.c_void_p
    lib.pool_aligned_free.argtypes = [ct.c_void_p, ct.c_void_p]
    lib.pool_aligned_free.restype = None

    # stats & locking
    lib.pool_get_stats.argtypes = [ct.c_void_p, ct.c_void_p]
    lib.pool_get_stats.restype = ct.c_int
    lib.pool_set_lock.argtypes = [ct.c_void_p, ct.c_void_p, ct.c_void_p,
                                   ct.c_void_p]
    lib.pool_set_lock.restype = ct.c_int

    return lib


@pytest.fixture
def pool_and_region(lib):
    """Create a 1 MB pool; tear it down after the test."""
    region = (ct.c_char * REGION_SIZE)()
    pool = lib.pool_create(region, REGION_SIZE)
    assert pool is not None, "pool_create returned NULL for 1 MB region"
    yield pool, region
    lib.pool_destroy(pool)


def _stats(lib, pool):
    s = PoolStats()
    rc = lib.pool_get_stats(pool, ct.byref(s))
    assert rc == 0, "pool_get_stats failed"
    return s


# ── Build & infrastructure tests ────────────────────────────────────

def test_meson_build(built):
    """Meson build produced a shared library."""
    assert os.path.exists(built), f"Library not found at {built}"
    assert os.path.getsize(built) > 0, "Library file is empty"


def test_symbol_visibility(built):
    """Only public API symbols should be exported as functions."""
    result = subprocess.run(
        ["nm", "-D", "--defined-only", built],
        capture_output=True, text=True)
    assert result.returncode == 0, f"nm failed: {result.stderr}"

    func_symbols = set()
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 3 and parts[1] == "T":
            # Strip version annotations (e.g. pool_create@@ALLOCATOR_1.0)
            sym_name = parts[2].split("@@")[0].split("@")[0]
            func_symbols.add(sym_name)

    unexpected = func_symbols - EXPECTED_SYMBOLS
    assert not unexpected, (
        f"Internal function symbols leaked from library: {unexpected}")

    missing = EXPECTED_SYMBOLS - func_symbols
    assert not missing, (
        f"Public API symbols missing from exports: {missing}")


_VALGRIND_SRC = r"""
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include "allocator.h"

int main(void) {
    size_t region_sz = 1024 * 1024;
    void *region = malloc(region_sz);
    if (!region) { perror("malloc"); return 2; }
    memset(region, 0, region_sz);

    mem_pool_t *pool = pool_create(region, region_sz);
    if (!pool) { fprintf(stderr, "pool_create failed\n"); free(region); return 3; }

    /* basic alloc/free */
    void *a = pool_malloc(pool, 100);
    if (!a) return 4;
    memset(a, 0xAB, 100);
    pool_free(pool, a);

    /* calloc zeroing */
    void *b = pool_calloc(pool, 10, 32);
    if (!b) return 5;
    unsigned char *bp = (unsigned char *)b;
    for (int i = 0; i < 320; i++) {
        if (bp[i] != 0) return 6;
    }
    pool_free(pool, b);

    /* realloc preserves data */
    void *c = pool_malloc(pool, 64);
    if (!c) return 7;
    memset(c, 0xCD, 64);
    void *c2 = pool_realloc(pool, c, 256);
    if (!c2) return 8;
    unsigned char *cp = (unsigned char *)c2;
    for (int i = 0; i < 64; i++) {
        if (cp[i] != 0xCD) return 9;
    }
    pool_free(pool, c2);

    /* aligned alloc */
    void *d = pool_aligned_malloc(pool, 256, 128);
    if (!d) return 10;
    if ((size_t)d % 256 != 0) return 11;
    memset(d, 0xEF, 128);
    pool_aligned_free(pool, d);

    /* stats */
    pool_stats_t stats;
    if (pool_get_stats(pool, &stats) != 0) return 12;
    if (stats.used_size != 0) return 13;

    pool_destroy(pool);
    free(region);
    return 0;
}
"""


def test_valgrind_clean(built):
    """Library must produce no Valgrind errors under exercised usage."""
    lib_dir = os.path.dirname(built)
    src = "/tmp/_valgrind_test.c"
    binary = "/tmp/_valgrind_test"

    with open(src, "w") as f:
        f.write(_VALGRIND_SRC)

    comp = subprocess.run(
        ["gcc", "-o", binary, src,
         "-I/app/include", f"-L{lib_dir}", "-lallocator",
         "-std=gnu11", "-O2",
         f"-Wl,-rpath,{lib_dir}"],
        capture_output=True, text=True)
    assert comp.returncode == 0, (
        f"Valgrind test compilation failed:\n{comp.stderr}")

    val = subprocess.run(
        ["valgrind", "--error-exitcode=42", "--leak-check=full",
         "--errors-for-leak-kinds=definite", binary],
        capture_output=True, text=True, timeout=60)
    assert val.returncode == 0, (
        f"Valgrind errors detected (exit {val.returncode}):\n{val.stderr}")


# ── Pool creation ────────────────────────────────────────────────────

def test_pool_create_basic(lib):
    region = (ct.c_char * REGION_SIZE)()
    pool = lib.pool_create(region, REGION_SIZE)
    assert pool is not None
    lib.pool_destroy(pool)


def test_pool_create_too_small(lib):
    region = (ct.c_char * 32)()
    pool = lib.pool_create(region, 32)
    assert pool is None, "pool_create should reject tiny regions"


# ── Basic alloc / free ───────────────────────────────────────────────

def test_basic_malloc(lib, pool_and_region):
    pool, _ = pool_and_region
    p = lib.pool_malloc(pool, 64)
    assert p is not None
    lib.pool_free(pool, p)


def test_write_read(lib, pool_and_region):
    pool, _ = pool_and_region
    p = lib.pool_malloc(pool, 256)
    assert p is not None
    pattern = bytes(range(256))
    ct.memmove(p, pattern, 256)
    buf = (ct.c_char * 256).from_address(p)
    assert bytes(buf) == pattern
    lib.pool_free(pool, p)


def test_multiple_no_overlap(lib, pool_and_region):
    pool, _ = pool_and_region
    N, SIZE = 20, 128
    ptrs = []
    for i in range(N):
        p = lib.pool_malloc(pool, SIZE)
        assert p is not None, f"allocation {i} failed"
        ct.memset(p, i & 0xFF, SIZE)
        ptrs.append(p)

    for i, p in enumerate(ptrs):
        buf = (ct.c_ubyte * SIZE).from_address(p)
        expected = i & 0xFF
        for j in range(SIZE):
            assert buf[j] == expected, (
                f"corruption block {i} offset {j}: "
                f"expected {expected}, got {buf[j]}")

    for p in ptrs:
        lib.pool_free(pool, p)


# ── Block splitting ──────────────────────────────────────────────────

def test_block_splitting(lib, pool_and_region):
    pool, _ = pool_and_region
    s0 = _stats(lib, pool)
    p = lib.pool_malloc(pool, 64)
    assert p is not None
    s1 = _stats(lib, pool)
    assert s1.num_free_blocks >= 1, "block should have been split"
    assert s1.used_size > 0
    assert s1.free_size < s0.free_size
    lib.pool_free(pool, p)


# ── Coalescing ───────────────────────────────────────────────────────

def test_coalescing_two(lib, pool_and_region):
    pool, _ = pool_and_region
    p1 = lib.pool_malloc(pool, 100)
    p2 = lib.pool_malloc(pool, 200)
    lib.pool_free(pool, p1)
    lib.pool_free(pool, p2)
    s = _stats(lib, pool)
    assert s.num_free_blocks == 1, (
        f"expected 1 coalesced block, got {s.num_free_blocks}")
    assert s.fragmentation == 0.0


def test_coalescing_three(lib, pool_and_region):
    pool, _ = pool_and_region
    p1 = lib.pool_malloc(pool, 100)
    p2 = lib.pool_malloc(pool, 100)
    p3 = lib.pool_malloc(pool, 100)
    # free in scrambled order: middle, first, last
    lib.pool_free(pool, p2)
    lib.pool_free(pool, p1)
    lib.pool_free(pool, p3)
    s = _stats(lib, pool)
    assert s.num_free_blocks == 1


def test_coalescing_reverse(lib, pool_and_region):
    pool, _ = pool_and_region
    ptrs = [lib.pool_malloc(pool, 64) for _ in range(10)]
    assert all(p is not None for p in ptrs)
    for p in reversed(ptrs):
        lib.pool_free(pool, p)
    s = _stats(lib, pool)
    assert s.num_free_blocks == 1


# ── Aligned allocation ──────────────────────────────────────────────

def test_aligned_malloc_various(lib, pool_and_region):
    pool, _ = pool_and_region
    for align in [16, 32, 64, 128, 256, 512, 1024, 4096]:
        p = lib.pool_aligned_malloc(pool, align, 100)
        assert p is not None, f"aligned_malloc(align={align}) failed"
        assert p % align == 0, (
            f"pointer {p:#x} not aligned to {align}")
        ct.memset(p, 0xAB, 100)
        lib.pool_aligned_free(pool, p)


def test_aligned_write_read(lib, pool_and_region):
    pool, _ = pool_and_region
    p = lib.pool_aligned_malloc(pool, 64, 200)
    assert p is not None and p % 64 == 0
    pattern = bytes([0xCD] * 200)
    ct.memmove(p, pattern, 200)
    buf = (ct.c_char * 200).from_address(p)
    assert bytes(buf) == pattern
    lib.pool_aligned_free(pool, p)


def test_aligned_invalid_alignment(lib, pool_and_region):
    pool, _ = pool_and_region
    p = lib.pool_aligned_malloc(pool, 3, 100)  # 3 is not a power of 2
    assert p is None


# ── Calloc ───────────────────────────────────────────────────────────

def test_calloc_zeroed(lib, pool_and_region):
    pool, _ = pool_and_region
    p = lib.pool_calloc(pool, 50, 8)
    assert p is not None
    buf = (ct.c_ubyte * 400).from_address(p)
    assert all(b == 0 for b in buf), "calloc memory not zeroed"
    lib.pool_free(pool, p)


def test_calloc_after_dirty(lib, pool_and_region):
    pool, _ = pool_and_region
    p1 = lib.pool_malloc(pool, 256)
    ct.memset(p1, 0xFF, 256)
    lib.pool_free(pool, p1)
    p2 = lib.pool_calloc(pool, 32, 8)
    assert p2 is not None
    buf = (ct.c_ubyte * 256).from_address(p2)
    assert all(b == 0 for b in buf), "calloc didn't zero dirty memory"
    lib.pool_free(pool, p2)


# ── Realloc ──────────────────────────────────────────────────────────

def test_realloc_grow(lib, pool_and_region):
    pool, _ = pool_and_region
    p = lib.pool_malloc(pool, 100)
    pattern = bytes(range(100))
    ct.memmove(p, pattern, 100)
    p2 = lib.pool_realloc(pool, p, 300)
    assert p2 is not None
    buf = (ct.c_char * 100).from_address(p2)
    assert bytes(buf) == pattern, "realloc didn't preserve data"
    lib.pool_free(pool, p2)


def test_realloc_shrink(lib, pool_and_region):
    pool, _ = pool_and_region
    p = lib.pool_malloc(pool, 400)
    pattern = bytes([0xBE] * 100)
    ct.memmove(p, pattern, 100)
    p2 = lib.pool_realloc(pool, p, 100)
    assert p2 is not None
    buf = (ct.c_char * 100).from_address(p2)
    assert bytes(buf) == pattern
    lib.pool_free(pool, p2)


def test_realloc_inplace(lib, pool_and_region):
    pool, _ = pool_and_region
    p1 = lib.pool_malloc(pool, 128)
    p2 = lib.pool_malloc(pool, 256)
    pattern = bytes(range(128))
    ct.memmove(p1, pattern, 128)

    lib.pool_free(pool, p2)  # free the block right after p1

    p1_new = lib.pool_realloc(pool, p1, 300)
    assert p1_new is not None
    assert p1_new == p1, "realloc should have grown in place"
    buf = (ct.c_char * 128).from_address(p1_new)
    assert bytes(buf) == pattern
    lib.pool_free(pool, p1_new)


def test_realloc_null_is_malloc(lib, pool_and_region):
    pool, _ = pool_and_region
    p = lib.pool_realloc(pool, None, 100)
    assert p is not None, "realloc(NULL, n) should act like malloc"
    lib.pool_free(pool, p)


# ── Statistics ───────────────────────────────────────────────────────

def test_stats_initial(lib, pool_and_region):
    pool, _ = pool_and_region
    s = _stats(lib, pool)
    assert s.total_size > 0
    assert s.used_size == 0
    assert s.free_size == s.total_size
    assert s.num_allocations == 0
    assert s.num_frees == 0
    assert s.num_free_blocks == 1
    assert s.largest_free_block == s.total_size
    assert s.fragmentation == 0.0


def test_stats_after_alloc_free(lib, pool_and_region):
    pool, _ = pool_and_region
    p = lib.pool_malloc(pool, 200)
    s1 = _stats(lib, pool)
    assert s1.used_size > 0
    assert s1.num_allocations == 1

    lib.pool_free(pool, p)
    s2 = _stats(lib, pool)
    assert s2.used_size == 0
    assert s2.num_frees == 1
    assert s2.free_size == s2.total_size


def test_fragmentation_ratio(lib, pool_and_region):
    pool, _ = pool_and_region
    ptrs = [lib.pool_malloc(pool, 1000) for _ in range(5)]
    assert all(p is not None for p in ptrs)
    # free alternating -> 2 non-adjacent holes
    lib.pool_free(pool, ptrs[1])
    lib.pool_free(pool, ptrs[3])
    s = _stats(lib, pool)
    assert s.num_free_blocks >= 2, (
        f"expected >=2 free blocks, got {s.num_free_blocks}")
    assert 0.0 < s.fragmentation < 1.0
    # clean up
    lib.pool_free(pool, ptrs[0])
    lib.pool_free(pool, ptrs[2])
    lib.pool_free(pool, ptrs[4])


# ── Pool isolation ───────────────────────────────────────────────────

def test_pool_isolation(lib):
    r1 = (ct.c_char * REGION_SIZE)()
    r2 = (ct.c_char * REGION_SIZE)()
    p1 = lib.pool_create(r1, REGION_SIZE)
    p2 = lib.pool_create(r2, REGION_SIZE)
    assert p1 and p2

    a = lib.pool_malloc(p1, 512)
    assert a is not None

    s2 = _stats(lib, p2)
    assert s2.used_size == 0 and s2.num_allocations == 0

    lib.pool_free(p1, a)
    s1 = _stats(lib, p1)
    assert s1.num_frees == 1
    s2 = _stats(lib, p2)
    assert s2.num_frees == 0

    lib.pool_destroy(p1)
    lib.pool_destroy(p2)


# ── Edge cases ───────────────────────────────────────────────────────

def test_malloc_zero(lib, pool_and_region):
    pool, _ = pool_and_region
    assert lib.pool_malloc(pool, 0) is None


def test_free_null(lib, pool_and_region):
    pool, _ = pool_and_region
    lib.pool_free(pool, None)  # must not crash


# ── Stress test ──────────────────────────────────────────────────────

def test_stress_random(lib):
    region = (ct.c_char * (4 * 1024 * 1024))()
    pool = lib.pool_create(region, 4 * 1024 * 1024)
    assert pool is not None

    rng = random.Random(42)
    allocs = []  # list of (ptr, size, tag)

    for _ in range(5000):
        if len(allocs) < 200 and (not allocs or rng.random() < 0.6):
            sz = rng.randint(1, 2048)
            p = lib.pool_malloc(pool, sz)
            if p:
                tag = rng.randint(0, 255)
                ct.memset(p, tag, sz)
                allocs.append((p, sz, tag))
        elif allocs:
            idx = rng.randint(0, len(allocs) - 1)
            p, sz, tag = allocs[idx]
            buf = (ct.c_ubyte * sz).from_address(p)
            for j in range(sz):
                assert buf[j] == tag, (
                    f"corruption offset {j}: expected {tag}, got {buf[j]}")
            lib.pool_free(pool, p)
            allocs[idx] = allocs[-1]
            allocs.pop()

    for p, sz, tag in allocs:
        lib.pool_free(pool, p)

    s = _stats(lib, pool)
    assert s.used_size == 0, f"leak: used_size={s.used_size}"
    assert s.num_free_blocks == 1, (
        f"incomplete coalesce: {s.num_free_blocks} free blocks")

    lib.pool_destroy(pool)


# ── Thread safety (compiled C test) ──────────────────────────────────

_THREAD_TEST_SRC = r"""
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdatomic.h>
#include <stdint.h>
#include "allocator.h"

#define POOL_SIZE  (4 * 1024 * 1024)
#define N_THREADS  8
#define ITERS      500
#define MAX_ALLOCS 50
#define MAX_SZ     256

static pthread_mutex_t mtx = PTHREAD_MUTEX_INITIALIZER;
static void lock_fn(void *c)   { pthread_mutex_lock((pthread_mutex_t *)c); }
static void unlock_fn(void *c) { pthread_mutex_unlock((pthread_mutex_t *)c); }
static atomic_int errors = 0;

static void *worker(void *arg) {
    mem_pool_t *pool = (mem_pool_t *)arg;
    void         *ptrs[MAX_ALLOCS];
    size_t        sizes[MAX_ALLOCS];
    unsigned char tags[MAX_ALLOCS];
    int count = 0;
    unsigned seed = (unsigned)(uintptr_t)pthread_self();

    for (int i = 0; i < ITERS; i++) {
        if (count < MAX_ALLOCS && (count == 0 || rand_r(&seed) % 3 != 0)) {
            size_t sz = (rand_r(&seed) % MAX_SZ) + 1;
            void  *p  = pool_malloc(pool, sz);
            if (p) {
                unsigned char tag = (unsigned char)(rand_r(&seed) & 0xFF);
                memset(p, tag, sz);
                ptrs[count]  = p;
                sizes[count] = sz;
                tags[count]  = tag;
                count++;
            }
        } else if (count > 0) {
            int idx = rand_r(&seed) % count;
            unsigned char *data = (unsigned char *)ptrs[idx];
            for (size_t j = 0; j < sizes[idx]; j++) {
                if (data[j] != tags[idx]) {
                    atomic_fetch_add(&errors, 1);
                    /* free remaining and bail */
                    for (int k = 0; k < count; k++) pool_free(pool, ptrs[k]);
                    return NULL;
                }
            }
            pool_free(pool, ptrs[idx]);
            ptrs[idx]  = ptrs[count - 1];
            sizes[idx] = sizes[count - 1];
            tags[idx]  = tags[count - 1];
            count--;
        }
    }
    for (int i = 0; i < count; i++) pool_free(pool, ptrs[i]);
    return NULL;
}

int main(void) {
    void *region = malloc(POOL_SIZE);
    if (!region) { fprintf(stderr, "malloc region failed\n"); return 2; }

    mem_pool_t *pool = pool_create(region, POOL_SIZE);
    if (!pool)   { fprintf(stderr, "pool_create failed\n"); return 3; }

    pool_set_lock(pool, lock_fn, unlock_fn, &mtx);

    pthread_t thr[N_THREADS];
    for (int i = 0; i < N_THREADS; i++)
        pthread_create(&thr[i], NULL, worker, pool);
    for (int i = 0; i < N_THREADS; i++)
        pthread_join(thr[i], NULL);

    int err = atomic_load(&errors);
    pool_destroy(pool);
    free(region);
    return err ? 1 : 0;
}
"""


def test_thread_safety(built):
    lib_dir = os.path.dirname(built)
    src = "/tmp/_alloc_thread_test.c"
    binary = "/tmp/_alloc_thread_test"
    with open(src, "w") as f:
        f.write(_THREAD_TEST_SRC)

    comp = subprocess.run(
        ["gcc", "-o", binary, src,
         "-I/app/include", f"-L{lib_dir}", "-lallocator",
         "-pthread", "-std=gnu11", "-O2",
         f"-Wl,-rpath,{lib_dir}"],
        capture_output=True, text=True)
    assert comp.returncode == 0, (
        f"thread-test compilation failed:\n{comp.stderr}")

    run = subprocess.run([binary], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, (
        f"thread-safety test failed (exit {run.returncode}):\n"
        f"{run.stdout}\n{run.stderr}")
