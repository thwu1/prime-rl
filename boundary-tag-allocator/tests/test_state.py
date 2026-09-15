
import os
import subprocess
import pytest

ALLOC_LIB = "/app/libmyalloc.so"
TEST_BIN_DIR = "/tmp/alloc_tests"

# ---------------------------------------------------------------------------
# Embedded C test programs
# ---------------------------------------------------------------------------

TEST_BASIC = r"""
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

int main(void) {
    /* malloc + write + read */
    char *p = malloc(256);
    if (!p) { fprintf(stderr, "malloc(256) failed\n"); return 1; }
    for (int i = 0; i < 256; i++) p[i] = (char)(i & 0xFF);
    for (int i = 0; i < 256; i++) {
        if (p[i] != (char)(i & 0xFF)) { fprintf(stderr, "data corruption\n"); return 1; }
    }
    free(p);

    /* Multiple non-overlapping allocations */
    char *a = malloc(100);
    char *b = malloc(100);
    char *c = malloc(100);
    if (!a || !b || !c) return 1;
    memset(a, 'A', 100);
    memset(b, 'B', 100);
    memset(c, 'C', 100);
    for (int i = 0; i < 100; i++) {
        if (a[i] != 'A' || b[i] != 'B' || c[i] != 'C') return 1;
    }
    free(a); free(b); free(c);

    /* calloc zeroing */
    int *arr = calloc(100, sizeof(int));
    if (!arr) return 1;
    for (int i = 0; i < 100; i++) {
        if (arr[i] != 0) { fprintf(stderr, "calloc not zero\n"); return 1; }
    }
    free(arr);

    /* realloc preserves data */
    char *r = malloc(50);
    if (!r) return 1;
    for (int i = 0; i < 50; i++) r[i] = 'R';
    r = realloc(r, 200);
    if (!r) return 1;
    for (int i = 0; i < 50; i++) {
        if (r[i] != 'R') { fprintf(stderr, "realloc corrupted\n"); return 1; }
    }
    free(r);

    /* Various sizes */
    for (int sz = 1; sz <= 8192; sz = sz * 2 + 1) {
        char *x = malloc(sz);
        if (!x) return 1;
        memset(x, 0x42, sz);
        free(x);
    }

    printf("PASS\n");
    return 0;
}
"""

TEST_ALIGN = r"""
#include <stdlib.h>
#include <stdio.h>
#include <stdint.h>

int main(void) {
    /* Single-allocation sweep */
    for (int size = 1; size <= 4096; size++) {
        void *p = malloc(size);
        if (!p) { fprintf(stderr, "malloc(%d) failed\n", size); return 1; }
        if ((uintptr_t)p % 16 != 0) {
            fprintf(stderr, "FAIL: %p not 16-aligned for size %d\n", p, size);
            return 1;
        }
        free(p);
    }

    /* Simultaneous allocations */
    void *ptrs[200];
    for (int i = 0; i < 200; i++) {
        ptrs[i] = malloc(1 + i * 7);
        if (!ptrs[i]) return 1;
        if ((uintptr_t)ptrs[i] % 16 != 0) {
            fprintf(stderr, "FAIL: %p not aligned (idx %d)\n", ptrs[i], i);
            return 1;
        }
    }
    for (int i = 0; i < 200; i++) free(ptrs[i]);

    printf("PASS\n");
    return 0;
}
"""

TEST_EDGE = r"""
#include <stdlib.h>
#include <stdio.h>
#include <stddef.h>

int main(void) {
    /* malloc(0) */
    void *z = malloc(0);
    if (z != NULL) free(z);   /* either NULL or freeable */

    /* free(NULL) must not crash */
    free(NULL);
    free(NULL);

    /* realloc(NULL, n) == malloc(n) */
    void *p = realloc(NULL, 100);
    if (!p) { fprintf(stderr, "realloc(NULL,100) failed\n"); return 1; }
    free(p);

    /* realloc(ptr, 0) frees */
    void *q = malloc(100);
    if (!q) return 1;
    void *r = realloc(q, 0);
    if (r) free(r);

    /* calloc overflow */
    void *ov = calloc((size_t)-1, (size_t)-1);
    if (ov != NULL) { fprintf(stderr, "calloc overflow missed\n"); return 1; }

    printf("PASS\n");
    return 0;
}
"""

TEST_COALESCE = r"""
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>

int main(void) {
    /* Flush the free list so subsequent allocations come from fresh heap */
    void *flush = malloc(65536);
    if (!flush) return 1;
    free(flush);

    /* Canary prevents backward coalescing past our region */
    void *canary1 = malloc(64);

    char *a = malloc(1024);
    char *b = malloc(1024);
    char *c = malloc(1024);

    /* Canary prevents forward coalescing past our region */
    void *canary2 = malloc(64);

    if (!canary1 || !a || !b || !c || !canary2) return 1;

    uintptr_t a_addr = (uintptr_t)a;
    uintptr_t c_end  = (uintptr_t)c + 1024;

    /* Free a, b, c — should coalesce into one block */
    free(a);
    free(b);
    free(c);

    /* 2500 bytes exceeds any single 1024-byte block; needs coalesced space */
    char *d = malloc(2500);
    if (!d) {
        fprintf(stderr, "FAIL: 2500-byte alloc failed after freeing 3x1024\n");
        free(canary1); free(canary2);
        return 1;
    }

    uintptr_t d_addr = (uintptr_t)d;
    if (d_addr >= a_addr && d_addr < c_end) {
        memset(d, 'D', 2500);
        free(d); free(canary1); free(canary2);
        printf("PASS\n");
        return 0;
    }

    fprintf(stderr, "FAIL: d=%p outside coalesced range [%p, %p)\n",
            (void *)d_addr, (void *)a_addr, (void *)c_end);
    free(d); free(canary1); free(canary2);
    return 1;
}
"""

TEST_SPLIT = r"""
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>

int main(void) {
    /* Flush free list */
    void *flush = malloc(65536);
    if (!flush) return 1;
    free(flush);

    void *canary1 = malloc(64);

    char *big = malloc(8192);
    if (!big) return 1;
    uintptr_t big_addr = (uintptr_t)big;
    uintptr_t big_end  = big_addr + 8192;

    void *canary2 = malloc(64);
    if (!canary1 || !canary2) return 1;

    free(big);

    /* Small allocation should come from the freed big block (splitting) */
    char *s1 = malloc(128);
    if (!s1) return 1;
    uintptr_t s1_addr = (uintptr_t)s1;
    if (s1_addr < big_addr || s1_addr >= big_end) {
        fprintf(stderr, "FAIL: s1=%p outside big block [%p,%p)\n",
                (void *)s1_addr, (void *)big_addr, (void *)big_end);
        free(s1); free(canary1); free(canary2);
        return 1;
    }

    /* Second allocation from the split remainder */
    char *s2 = malloc(4096);
    if (!s2) {
        fprintf(stderr, "FAIL: 4096-byte alloc from split remainder failed\n");
        free(s1); free(canary1); free(canary2);
        return 1;
    }
    uintptr_t s2_addr = (uintptr_t)s2;
    if (s2_addr < big_addr || s2_addr >= big_end) {
        fprintf(stderr, "FAIL: s2=%p outside big block [%p,%p)\n",
                (void *)s2_addr, (void *)big_addr, (void *)big_end);
        free(s1); free(s2); free(canary1); free(canary2);
        return 1;
    }

    /* Verify no overlap via data integrity */
    memset(s1, 'A', 128);
    memset(s2, 'B', 4096);
    for (int i = 0; i < 128; i++) {
        if (((char *)s1)[i] != 'A') {
            fprintf(stderr, "FAIL: s1 data corruption\n");
            free(s1); free(s2); free(canary1); free(canary2);
            return 1;
        }
    }

    free(s1); free(s2); free(canary1); free(canary2);
    printf("PASS\n");
    return 0;
}
"""

TEST_STRESS = r"""
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>

static unsigned int seed = 12345;
static unsigned int my_rand(void) {
    seed = seed * 1103515245u + 12345u;
    return (seed >> 16) & 0x7FFF;
}

int main(void) {
    enum { SLOTS = 1000, ITERS = 50000 };
    void  *ptrs[SLOTS];
    size_t sizes[SLOTS];
    int    used[SLOTS];

    memset(used, 0, sizeof(used));

    for (int it = 0; it < ITERS; it++) {
        int idx = my_rand() % SLOTS;

        if (used[idx]) {
            int action = my_rand() % 3;
            if (action == 0) {
                free(ptrs[idx]);
                used[idx] = 0;
            } else if (action == 1) {
                size_t ns = (my_rand() % 4096) + 1;
                size_t old_size = sizes[idx];
                void *np = realloc(ptrs[idx], ns);
                if (np) {
                    /* Verify preserved bytes before re-stamping */
                    char expected = (char)(idx & 0xFF);
                    size_t preserved = (old_size < ns) ? old_size : ns;
                    size_t ck = preserved < 8 ? preserved : 8;
                    for (size_t j = 0; j < ck; j++) {
                        if (((char *)np)[j] != expected) {
                            fprintf(stderr, "FAIL: realloc corruption iter=%d idx=%d byte=%zu\n",
                                    it, idx, j);
                            return 1;
                        }
                    }
                    ptrs[idx] = np;
                    sizes[idx] = ns;
                    /* Re-stamp to cover the full check range */
                    size_t fs = ns < 8 ? ns : 8;
                    memset(np, expected, fs);
                }
            } else {
                char expected = (char)(idx & 0xFF);
                size_t ck = sizes[idx] < 8 ? sizes[idx] : 8;
                for (size_t j = 0; j < ck; j++) {
                    if (((char *)ptrs[idx])[j] != expected) {
                        fprintf(stderr, "FAIL: corruption iter=%d idx=%d\n", it, idx);
                        return 1;
                    }
                }
            }
        } else {
            size_t sz = (my_rand() % 4096) + 1;
            ptrs[idx] = malloc(sz);
            if (ptrs[idx]) {
                sizes[idx] = sz;
                used[idx] = 1;
                char fill = (char)(idx & 0xFF);
                size_t fs = sz < 8 ? sz : 8;
                memset(ptrs[idx], fill, fs);
            }
        }
    }

    for (int i = 0; i < SLOTS; i++) {
        if (used[i]) free(ptrs[i]);
    }

    printf("PASS\n");
    return 0;
}
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def compile_test_programs():
    """Write and compile all embedded C test programs."""
    os.makedirs(TEST_BIN_DIR, exist_ok=True)
    programs = {
        "test_basic":    TEST_BASIC,
        "test_align":    TEST_ALIGN,
        "test_edge":     TEST_EDGE,
        "test_coalesce": TEST_COALESCE,
        "test_split":    TEST_SPLIT,
        "test_stress":   TEST_STRESS,
    }
    for name, source in programs.items():
        src = os.path.join(TEST_BIN_DIR, f"{name}.c")
        out = os.path.join(TEST_BIN_DIR, name)
        with open(src, "w") as f:
            f.write(source)
        r = subprocess.run(
            ["gcc", "-O0", "-o", out, src, "-lpthread", "-Wno-deprecated-declarations"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"Compile {name} failed: {r.stderr}"


def _run_preload(binary, args=None, timeout=60):
    env = os.environ.copy()
    env["LD_PRELOAD"] = ALLOC_LIB
    cmd = [binary] + (args or [])
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, env=env)


# ---------------------------------------------------------------------------
# Tests — library structure
# ---------------------------------------------------------------------------

class TestLibraryStructure:
    def test_library_exists(self):
        assert os.path.isfile(ALLOC_LIB), f"{ALLOC_LIB} not found"

    def test_is_shared_object(self):
        r = subprocess.run(["file", ALLOC_LIB], capture_output=True, text=True)
        assert r.returncode == 0
        out = r.stdout.lower()
        assert "elf" in out and "shared object" in out, \
            f"Not a valid ELF shared object: {r.stdout}"

    def test_exports_required_symbols(self):
        r = subprocess.run(["nm", "-D", ALLOC_LIB], capture_output=True, text=True)
        assert r.returncode == 0
        for sym in ("malloc", "free", "calloc", "realloc"):
            assert sym in r.stdout, f"Symbol '{sym}' not exported"


# ---------------------------------------------------------------------------
# Tests — correctness (standard C semantics)
# ---------------------------------------------------------------------------

class TestCorrectness:
    def test_basic_alloc_free(self):
        r = _run_preload(f"{TEST_BIN_DIR}/test_basic")
        assert r.returncode == 0, f"Crashed: {r.stderr}"
        assert "PASS" in r.stdout, f"Failed: {r.stdout}{r.stderr}"

    def test_alignment_16byte(self):
        r = _run_preload(f"{TEST_BIN_DIR}/test_align")
        assert r.returncode == 0, f"Crashed: {r.stderr}"
        assert "PASS" in r.stdout, f"Failed: {r.stdout}{r.stderr}"

    def test_edge_cases(self):
        r = _run_preload(f"{TEST_BIN_DIR}/test_edge")
        assert r.returncode == 0, f"Crashed: {r.stderr}"
        assert "PASS" in r.stdout, f"Failed: {r.stdout}{r.stderr}"


# ---------------------------------------------------------------------------
# Tests — memory reclamation (coalescing + splitting)
# ---------------------------------------------------------------------------

class TestMemoryReclamation:
    def test_coalescing(self):
        r = _run_preload(f"{TEST_BIN_DIR}/test_coalesce")
        assert r.returncode == 0, f"Crashed: {r.stderr}"
        assert "PASS" in r.stdout, f"Failed: {r.stdout}{r.stderr}"

    def test_splitting(self):
        r = _run_preload(f"{TEST_BIN_DIR}/test_split")
        assert r.returncode == 0, f"Crashed: {r.stderr}"
        assert "PASS" in r.stdout, f"Failed: {r.stdout}{r.stderr}"


# ---------------------------------------------------------------------------
# Tests — LD_PRELOAD compatibility
# ---------------------------------------------------------------------------

class TestCompatibility:
    def test_bin_ls(self):
        r = _run_preload("/bin/ls", args=["/"])
        assert r.returncode == 0, f"/bin/ls crashed: {r.stderr}"
        assert "usr" in r.stdout or "etc" in r.stdout, \
            f"Unexpected output: {r.stdout}"

    def test_bin_echo(self):
        r = _run_preload("/bin/echo", args=["hello", "world"])
        assert r.returncode == 0, f"/bin/echo crashed: {r.stderr}"
        assert "hello world" in r.stdout

    def test_bin_cat(self):
        test_file = "/tmp/alloc_test_catfile.txt"
        with open(test_file, "w") as f:
            f.write("allocator_cat_test_7890\n")
        r = _run_preload("/bin/cat", args=[test_file])
        assert r.returncode == 0, f"/bin/cat crashed: {r.stderr}"
        assert "allocator_cat_test_7890" in r.stdout


# ---------------------------------------------------------------------------
# Tests — stress
# ---------------------------------------------------------------------------

class TestStress:
    def test_random_stress(self):
        r = _run_preload(f"{TEST_BIN_DIR}/test_stress", timeout=120)
        assert r.returncode == 0, f"Crashed: {r.stderr}"
        assert "PASS" in r.stdout, f"Failed: {r.stdout}{r.stderr}"
