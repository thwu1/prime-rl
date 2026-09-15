"""
Test suite for hardened memory allocator.

Compiles small C programs against /app/allocator.c and verifies
correctness, security hardening, statistics, and performance.

"""

import os
import signal
import subprocess
import tempfile

import pytest

COMPILE_FLAGS = ["-O0", "-g", "-std=gnu11", "-I/app", "-Wall"]


def _compile_and_run(c_code, name, timeout=30, extra_cflags=None):
    """Compile C source against allocator.c, run, return CompletedProcess."""
    src = f"/tmp/_test_{name}.c"
    binary = f"/tmp/_test_{name}"
    with open(src, "w") as f:
        f.write(c_code)

    flags = COMPILE_FLAGS.copy()
    if extra_cflags:
        flags.extend(extra_cflags)

    comp = subprocess.run(
        ["gcc"] + flags + [src, "/app/allocator.c", "-o", binary],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert comp.returncode == 0, f"Compilation of {name} failed:\n{comp.stderr}"

    result = subprocess.run(
        [binary], capture_output=True, text=True, timeout=timeout
    )

    # cleanup
    for p in (src, binary):
        if os.path.exists(p):
            os.unlink(p)

    return result


def _assert_signal(result, sigs, msg=""):
    """Assert the process was killed by one of the given signal numbers."""
    for s in sigs:
        if result.returncode == -s or result.returncode == 128 + s:
            return
    pytest.fail(
        f"Expected signal(s) {sigs}, got returncode {result.returncode}. {msg}\n"
        f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
    )


# ── Correctness ──────────────────────────────────────────────────────

class TestBasicAllocation:
    """Core alloc / free / realloc correctness."""

    def test_basic_alloc_free(self):
        code = r"""
#include "allocator.h"
#include <string.h>
#include <assert.h>
#include <stdint.h>

int main(void) {
    halloc_init();

    /* halloc(0) -> NULL */
    assert(halloc(0) == NULL);

    /* hfree(NULL, 0) is a no-op */
    hfree(NULL, 0);

    /* Single allocation, data integrity */
    char *p1 = halloc(100);
    assert(p1 != NULL);
    memset(p1, 'A', 100);
    for (int i = 0; i < 100; i++) assert(p1[i] == 'A');

    /* Multiple allocations, no overlap */
    char *p2 = halloc(200);
    char *p3 = halloc(50);
    assert(p2 && p3);
    assert(p1 != p2 && p2 != p3 && p1 != p3);
    memset(p2, 'B', 200);
    memset(p3, 'C', 50);
    for (int i = 0; i < 100; i++) assert(p1[i] == 'A');

    /* Free and re-allocate */
    hfree(p2, 200);
    char *p4 = halloc(200);
    assert(p4 != NULL);
    memset(p4, 'D', 200);

    hfree(p1, 100);
    hfree(p3, 50);
    hfree(p4, 200);
    return 0;
}
"""
        r = _compile_and_run(code, "basic")
        assert r.returncode == 0, f"basic alloc failed: {r.stderr}"

    def test_all_size_classes(self):
        code = r"""
#include "allocator.h"
#include <string.h>
#include <assert.h>
#include <stdint.h>

int main(void) {
    halloc_init();
    size_t sizes[] = {16,32,48,64,96,128,192,256,384,512,1024,2048};
    void *ptrs[12];
    for (int i = 0; i < 12; i++) {
        ptrs[i] = halloc(sizes[i]);
        assert(ptrs[i] != NULL);
        memset(ptrs[i], (unsigned char)(i+1), sizes[i]);
    }
    for (int i = 0; i < 12; i++) {
        unsigned char *p = ptrs[i];
        for (size_t j = 0; j < sizes[i]; j++)
            assert(p[j] == (unsigned char)(i+1));
        hfree(ptrs[i], sizes[i]);
    }
    return 0;
}
"""
        r = _compile_and_run(code, "classes")
        assert r.returncode == 0, f"size class test failed: {r.stderr}"

    def test_alignment(self):
        code = r"""
#include "allocator.h"
#include <assert.h>
#include <stdint.h>

int main(void) {
    halloc_init();
    for (int i = 1; i <= 200; i++) {
        void *p = halloc(i);
        assert(p != NULL);
        assert(((uintptr_t)p & 15) == 0);
        hfree(p, i);
    }
    /* Large alloc alignment */
    void *q = halloc(8192);
    assert(q != NULL);
    assert(((uintptr_t)q & 15) == 0);
    hfree(q, 8192);
    return 0;
}
"""
        r = _compile_and_run(code, "align")
        assert r.returncode == 0, f"alignment test failed: {r.stderr}"

    def test_realloc(self):
        code = r"""
#include "allocator.h"
#include <string.h>
#include <assert.h>

int main(void) {
    halloc_init();

    /* realloc(NULL, _, n) == halloc(n) */
    char *p1 = hrealloc(NULL, 0, 100);
    assert(p1 != NULL);
    memset(p1, 'X', 100);

    /* Grow, data preserved */
    char *p2 = hrealloc(p1, 100, 200);
    assert(p2 != NULL);
    for (int i = 0; i < 100; i++) assert(p2[i] == 'X');

    /* Shrink, data preserved */
    char *p3 = hrealloc(p2, 200, 50);
    assert(p3 != NULL);
    for (int i = 0; i < 50; i++) assert(p3[i] == 'X');

    hfree(p3, 50);

    /* Cross size-class realloc */
    char *p4 = halloc(16);
    memset(p4, 'A', 16);
    char *p5 = hrealloc(p4, 16, 256);
    assert(p5 != NULL);
    for (int i = 0; i < 16; i++) assert(p5[i] == 'A');

    /* Small -> large realloc */
    memset(p5, 'B', 256);
    char *p6 = hrealloc(p5, 256, 4096);
    assert(p6 != NULL);
    for (int i = 0; i < 256; i++) assert(p6[i] == 'B');

    hfree(p6, 4096);
    return 0;
}
"""
        r = _compile_and_run(code, "realloc")
        assert r.returncode == 0, f"realloc test failed: {r.stderr}"

    def test_large_alloc(self):
        code = r"""
#include "allocator.h"
#include <string.h>
#include <assert.h>
#include <stdint.h>

int main(void) {
    halloc_init();

    /* Allocate several large blocks */
    char *p1 = halloc(4096);
    char *p2 = halloc(8192);
    char *p3 = halloc(65536);
    assert(p1 && p2 && p3);

    memset(p1, 'L', 4096);
    memset(p2, 'M', 8192);
    memset(p3, 'N', 65536);

    /* Verify data integrity */
    for (int i = 0; i < 4096; i++) assert(p1[i] == 'L');
    for (int i = 0; i < 8192; i++) assert(p2[i] == 'M');
    for (int i = 0; i < 65536; i++) assert(p3[i] == 'N');

    hfree(p1, 4096);
    hfree(p2, 8192);
    hfree(p3, 65536);
    return 0;
}
"""
        r = _compile_and_run(code, "large")
        assert r.returncode == 0, f"large alloc test failed: {r.stderr}"


# ── Security hardening ───────────────────────────────────────────────

class TestSecurity:
    """Overflow detection, double-free, scrubbing, fault isolation."""

    def test_overflow_past_allocation(self):
        """Overflowing past the allocation boundary must be detected
        by hfree and must abort the process."""
        code = r"""
#include "allocator.h"
#include <string.h>

int main(void) {
    halloc_init();
    char *p = halloc(64);
    if (!p) return 2;
    /* Write 72 bytes: 8 bytes past the 64-byte allocation
       must corrupt integrity metadata */
    memset(p, 0xFF, 72);
    /* hfree must detect the corruption and abort */
    hfree(p, 64);
    /* should not reach here */
    return 1;
}
"""
        r = _compile_and_run(code, "overflow_detect")
        _assert_signal(r, [signal.SIGABRT], "Buffer overflow past allocation not detected")

    def test_metadata_corruption(self):
        """Corrupting the allocator metadata preceding the user pointer
        must be detected on free."""
        code = r"""
#include "allocator.h"
#include <stdint.h>
#include <string.h>

int main(void) {
    halloc_init();
    char *p = halloc(64);
    if (!p) return 2;
    /* Corrupt 8 bytes at the very start of the metadata region
       preceding the user pointer (32 bytes before user_ptr). */
    memset(p - 32, 0xFF, 8);
    hfree(p, 64);
    return 1;
}
"""
        r = _compile_and_run(code, "metadata_corrupt")
        _assert_signal(r, [signal.SIGABRT], "Metadata corruption not detected")

    def test_double_free(self):
        """Freeing the same pointer twice must abort."""
        code = r"""
#include "allocator.h"

int main(void) {
    halloc_init();
    char *p = halloc(128);
    if (!p) return 2;
    hfree(p, 128);
    /* Second free: should abort */
    hfree(p, 128);
    return 1;
}
"""
        r = _compile_and_run(code, "double_free")
        _assert_signal(r, [signal.SIGABRT], "Double-free not detected")

    def test_memory_scrubbing(self):
        """Freed slab memory must be filled with 0xAB."""
        code = r"""
#include "allocator.h"
#include <string.h>
#include <assert.h>

int main(void) {
    halloc_init();
    char *p = halloc(64);
    if (!p) return 2;
    memset(p, 'Z', 64);
    /* Save pointer — memory stays mapped in the slab. */
    volatile char *saved = p;
    hfree(p, 64);
    /* Verify scrubbing (UB but deterministic with our allocator). */
    for (int i = 0; i < 64; i++) {
        if ((unsigned char)saved[i] != 0xAB) return 1;
    }
    return 0;
}
"""
        r = _compile_and_run(code, "scrub")
        assert r.returncode == 0, f"Memory scrubbing failed: {r.stderr}"

    def test_fault_isolation(self):
        """Large allocations must have inaccessible (---p) regions
        adjacent to the data mapping in /proc/self/maps."""
        code = r"""
#include "allocator.h"
#include <stdio.h>
#include <string.h>
#include <stdint.h>

int main(void) {
    halloc_init();
    char *p = halloc(8192);
    if (!p) return 2;
    memset(p, 'A', 8192);

    /* Print pointer value and /proc/self/maps for analysis */
    printf("PTR:%lx\n", (unsigned long)(uintptr_t)p);

    FILE *f = fopen("/proc/self/maps", "r");
    if (!f) return 2;
    char line[512];
    while (fgets(line, sizeof(line), f)) {
        printf("MAP:%s", line);
    }
    fclose(f);

    hfree(p, 8192);
    return 0;
}
"""
        r = _compile_and_run(code, "fault_iso", timeout=10)
        assert r.returncode == 0, f"Fault isolation program failed: {r.stderr}"

        # Parse output
        ptr = None
        maps = []
        for line in r.stdout.splitlines():
            if line.startswith("PTR:"):
                ptr = int(line[4:], 16)
            elif line.startswith("MAP:"):
                mapline = line[4:]
                parts = mapline.split()
                if len(parts) >= 2:
                    addrs = parts[0].split("-")
                    if len(addrs) == 2:
                        try:
                            start = int(addrs[0], 16)
                            end = int(addrs[1], 16)
                            perms = parts[1]
                            maps.append((start, end, perms))
                        except ValueError:
                            pass

        assert ptr is not None, "Could not parse pointer from output"

        # Find the rw-p mapping containing the user pointer
        data_map = None
        for start, end, perms in maps:
            if start <= ptr < end and "rw" in perms:
                data_map = (start, end, perms)
                break

        assert data_map is not None, (
            f"Could not find rw mapping for ptr {ptr:#x}"
        )

        # Verify inaccessible (---p) regions adjacent to the data mapping
        front_guard = False
        rear_guard = False
        for start, end, perms in maps:
            if perms.startswith("---"):
                if end == data_map[0]:
                    front_guard = True
                if start == data_map[1]:
                    rear_guard = True

        assert front_guard, (
            f"No front inaccessible region (---p) adjacent to data mapping "
            f"[{data_map[0]:#x}-{data_map[1]:#x}]"
        )
        assert rear_guard, (
            f"No rear inaccessible region (---p) adjacent to data mapping "
            f"[{data_map[0]:#x}-{data_map[1]:#x}]"
        )


# ── Statistics ───────────────────────────────────────────────────────

class TestStatistics:
    """halloc_get_stats must track allocations accurately."""

    def test_stats_tracking(self):
        code = r"""
#include "allocator.h"
#include <assert.h>

int main(void) {
    halloc_init();
    halloc_stats_t s;

    /* Initial state */
    halloc_get_stats(&s);
    assert(s.total_allocs == 0);
    assert(s.total_frees == 0);
    assert(s.bytes_allocated == 0);
    assert(s.large_allocs == 0);

    /* Three small allocations (exact size-class boundaries) */
    void *p1 = halloc(64);
    void *p2 = halloc(128);
    void *p3 = halloc(64);
    halloc_get_stats(&s);
    assert(s.total_allocs == 3);
    assert(s.total_frees == 0);
    assert(s.bytes_allocated == 64 + 128 + 64);
    assert(s.slab_pages > 0);
    assert(s.large_allocs == 0);

    /* Free one */
    hfree(p2, 128);
    halloc_get_stats(&s);
    assert(s.total_allocs == 3);
    assert(s.total_frees == 1);
    assert(s.bytes_allocated == 64 + 64);

    /* Large allocation */
    void *p4 = halloc(4096);
    halloc_get_stats(&s);
    assert(s.total_allocs == 4);
    assert(s.bytes_allocated == 64 + 64 + 4096);
    assert(s.large_allocs == 1);

    /* Free large */
    hfree(p4, 4096);
    halloc_get_stats(&s);
    assert(s.total_frees == 2);
    assert(s.large_allocs == 0);
    assert(s.bytes_allocated == 64 + 64);

    /* Cleanup */
    hfree(p1, 64);
    hfree(p3, 64);
    halloc_get_stats(&s);
    assert(s.total_frees == 4);
    assert(s.bytes_allocated == 0);

    return 0;
}
"""
        r = _compile_and_run(code, "stats")
        assert r.returncode == 0, f"Statistics test failed: {r.stderr}"


# ── Performance ──────────────────────────────────────────────────────

class TestPerformance:
    """The allocator must handle bulk alloc/free within a time budget."""

    def test_throughput(self):
        code = r"""
#include "allocator.h"
#include <time.h>
#include <assert.h>
#include <string.h>

#define N 100000

int main(void) {
    halloc_init();
    struct timespec start, end;
    void *ptrs[N];

    clock_gettime(CLOCK_MONOTONIC, &start);

    /* 5 rounds of uniform alloc/free (500K allocs + 500K frees) */
    for (int r = 0; r < 5; r++) {
        for (int i = 0; i < N; i++) {
            ptrs[i] = halloc(64);
            assert(ptrs[i] != NULL);
        }
        for (int i = 0; i < N; i++) {
            hfree(ptrs[i], 64);
        }
    }

    /* 5 rounds of mixed-size alloc/free */
    size_t sizes[] = {16, 32, 64, 128, 256};
    for (int r = 0; r < 5; r++) {
        for (int i = 0; i < N; i++) {
            size_t sz = sizes[i % 5];
            ptrs[i] = halloc(sz);
            assert(ptrs[i] != NULL);
        }
        for (int i = 0; i < N; i++) {
            size_t sz = sizes[i % 5];
            hfree(ptrs[i], sz);
        }
    }

    clock_gettime(CLOCK_MONOTONIC, &end);

    double elapsed = (end.tv_sec - start.tv_sec)
                   + (end.tv_nsec - start.tv_nsec) / 1e9;
    /* 2M operations should complete well within 30 seconds. */
    if (elapsed > 30.0) return 1;
    return 0;
}
"""
        r = _compile_and_run(code, "perf", timeout=60, extra_cflags=["-O2"])
        assert r.returncode == 0, f"Performance test failed (too slow): {r.stderr}"
