/* test_harness.c: comprehensive tests for walloc native port
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "walloc_native.h"

#define PASS(name) printf("PASS: %s\n", name)
#define FAIL(name, ...) do { printf("FAIL: %s - ", name); printf(__VA_ARGS__); printf("\n"); return 1; } while(0)

static int test_init(void) {
    walloc_init();
    PASS("init");
    return 0;
}

static int test_basic_malloc(void) {
    void *p1 = walloc_malloc(10);
    if (!p1) FAIL("basic_malloc", "malloc(10) returned NULL");
    void *p2 = walloc_malloc(100);
    if (!p2) FAIL("basic_malloc", "malloc(100) returned NULL");
    void *p3 = walloc_malloc(1000);
    if (!p3) FAIL("basic_malloc", "malloc(1000) returned NULL");

    /* verify memory is writable */
    memset(p1, 0xAA, 10);
    memset(p2, 0xBB, 100);
    memset(p3, 0xCC, 1000);

    /* verify no overlap */
    unsigned char *c1 = (unsigned char *)p1;
    unsigned char *c2 = (unsigned char *)p2;
    unsigned char *c3 = (unsigned char *)p3;
    for (int i = 0; i < 10; i++) {
        if (c1[i] != 0xAA) FAIL("basic_malloc", "p1 corrupted at offset %d", i);
    }
    for (int i = 0; i < 100; i++) {
        if (c2[i] != 0xBB) FAIL("basic_malloc", "p2 corrupted at offset %d", i);
    }
    for (int i = 0; i < 1000; i++) {
        if (c3[i] != 0xCC) FAIL("basic_malloc", "p3 corrupted at offset %d", i);
    }

    walloc_free(p1);
    walloc_free(p2);
    walloc_free(p3);
    PASS("basic_malloc");
    return 0;
}

static int test_usable_size_small(void) {
    /*
     * walloc has 10 small-object size classes:
     *   1, 2, 3, 4, 5, 6, 8, 10, 16, 32 granules (granule = 8 bytes)
     * granules_to_chunk_kind rounds UP to the next size class.
     */
    struct { size_t request; size_t expected; } cases[] = {
        {1,   8},    /* 1 granule */
        {8,   8},    /* 1 granule */
        {9,   16},   /* 2 granules */
        {16,  16},   /* 2 granules */
        {17,  24},   /* 3 granules */
        {24,  24},   /* 3 granules */
        {25,  32},   /* 4 granules */
        {32,  32},   /* 4 granules */
        {33,  40},   /* 5 granules */
        {40,  40},   /* 5 granules */
        {41,  48},   /* 6 granules */
        {48,  48},   /* 6 granules */
        {49,  64},   /* 8 granules (7 rounds up to 8) */
        {64,  64},   /* 8 granules */
        {65,  80},   /* 10 granules (9 rounds up to 10) */
        {80,  80},   /* 10 granules */
        {81,  128},  /* 16 granules (11 rounds up to 16) */
        {128, 128},  /* 16 granules */
        {129, 256},  /* 32 granules (17 rounds up to 32) */
        {256, 256},  /* 32 granules */
    };
    int n = sizeof(cases) / sizeof(cases[0]);

    for (int i = 0; i < n; i++) {
        void *p = walloc_malloc(cases[i].request);
        if (!p) FAIL("usable_size_small", "malloc(%zu) returned NULL", cases[i].request);

        size_t usable = walloc_malloc_usable_size(p);
        if (usable != cases[i].expected) {
            walloc_free(p);
            FAIL("usable_size_small",
                 "malloc_usable_size(malloc(%zu)) = %zu, expected %zu",
                 cases[i].request, usable, cases[i].expected);
        }
        walloc_free(p);
    }
    PASS("usable_size_small");
    return 0;
}

static int test_usable_size_large(void) {
    size_t sizes[] = {257, 500, 1000, 4096, 8192, 16384, 32768};
    int n = sizeof(sizes) / sizeof(sizes[0]);

    for (int i = 0; i < n; i++) {
        void *p = walloc_malloc(sizes[i]);
        if (!p) FAIL("usable_size_large", "malloc(%zu) returned NULL", sizes[i]);

        size_t usable = walloc_malloc_usable_size(p);
        if (usable < sizes[i]) {
            walloc_free(p);
            FAIL("usable_size_large",
                 "malloc_usable_size(malloc(%zu)) = %zu, expected >= %zu",
                 sizes[i], usable, sizes[i]);
        }
        walloc_free(p);
    }
    PASS("usable_size_large");
    return 0;
}

static int test_usable_size_null(void) {
    size_t usable = walloc_malloc_usable_size(NULL);
    if (usable != 0) FAIL("usable_size_null", "malloc_usable_size(NULL) = %zu, expected 0", usable);
    PASS("usable_size_null");
    return 0;
}

static int test_realloc_null(void) {
    void *p = walloc_realloc(NULL, 100);
    if (!p) FAIL("realloc_null", "realloc(NULL, 100) returned NULL");
    memset(p, 0xAA, 100);
    walloc_free(p);
    PASS("realloc_null");
    return 0;
}

static int test_realloc_zero(void) {
    void *p = walloc_malloc(100);
    if (!p) FAIL("realloc_zero", "malloc(100) returned NULL");
    memset(p, 0xAA, 100);

    void *r = walloc_realloc(p, 0);
    if (r != NULL) FAIL("realloc_zero", "realloc(ptr, 0) returned non-NULL");
    PASS("realloc_zero");
    return 0;
}

static int test_realloc_grow(void) {
    void *p = walloc_malloc(50);
    if (!p) FAIL("realloc_grow", "initial malloc failed");
    memset(p, 0x42, 50);

    void *p2 = walloc_realloc(p, 200);
    if (!p2) FAIL("realloc_grow", "realloc to 200 failed");

    unsigned char *cp = (unsigned char *)p2;
    for (int i = 0; i < 50; i++) {
        if (cp[i] != 0x42) {
            FAIL("realloc_grow", "data not preserved at offset %d: got 0x%02x, expected 0x42", i, cp[i]);
        }
    }

    walloc_free(p2);
    PASS("realloc_grow");
    return 0;
}

static int test_realloc_shrink(void) {
    void *p = walloc_malloc(500);
    if (!p) FAIL("realloc_shrink", "initial malloc failed");

    unsigned char *cp = (unsigned char *)p;
    for (int i = 0; i < 500; i++) {
        cp[i] = (unsigned char)(i & 0xFF);
    }

    void *p2 = walloc_realloc(p, 50);
    if (!p2) FAIL("realloc_shrink", "realloc to 50 returned NULL");

    cp = (unsigned char *)p2;
    for (int i = 0; i < 50; i++) {
        if (cp[i] != (unsigned char)(i & 0xFF)) {
            FAIL("realloc_shrink", "data not preserved at offset %d: got 0x%02x, expected 0x%02x",
                 i, cp[i], (unsigned char)(i & 0xFF));
        }
    }

    walloc_free(p2);
    PASS("realloc_shrink");
    return 0;
}

static int test_realloc_same_class(void) {
    /* malloc(10) -> 2 granules (16 bytes usable)
     * realloc to 15 -> still 2 granules, should return same pointer */
    void *p = walloc_malloc(10);
    if (!p) FAIL("realloc_same_class", "malloc(10) failed");
    memset(p, 0xEE, 10);

    void *p2 = walloc_realloc(p, 15);
    if (p2 != p) {
        FAIL("realloc_same_class",
             "realloc within same size class returned different pointer (%p vs %p)", p2, p);
    }

    /* verify data preserved */
    unsigned char *cp = (unsigned char *)p2;
    for (int i = 0; i < 10; i++) {
        if (cp[i] != 0xEE) {
            FAIL("realloc_same_class", "data corrupted at offset %d", i);
        }
    }

    walloc_free(p);
    PASS("realloc_same_class");
    return 0;
}

static int test_realloc_small_to_large(void) {
    void *p = walloc_malloc(100);
    if (!p) FAIL("realloc_small_to_large", "malloc(100) failed");
    memset(p, 0xCC, 100);

    void *p2 = walloc_realloc(p, 1000);
    if (!p2) FAIL("realloc_small_to_large", "realloc to 1000 failed");

    unsigned char *cp = (unsigned char *)p2;
    for (int i = 0; i < 100; i++) {
        if (cp[i] != 0xCC) {
            FAIL("realloc_small_to_large", "data not preserved at offset %d", i);
        }
    }

    size_t usable = walloc_malloc_usable_size(p2);
    if (usable < 1000) {
        FAIL("realloc_small_to_large", "usable size %zu < 1000 after realloc", usable);
    }

    walloc_free(p2);
    PASS("realloc_small_to_large");
    return 0;
}

static int test_realloc_large_to_small(void) {
    void *p = walloc_malloc(1000);
    if (!p) FAIL("realloc_large_to_small", "malloc(1000) failed");
    memset(p, 0xDD, 1000);

    void *p2 = walloc_realloc(p, 50);
    if (!p2) FAIL("realloc_large_to_small", "realloc to 50 returned NULL");

    unsigned char *cp = (unsigned char *)p2;
    for (int i = 0; i < 50; i++) {
        if (cp[i] != 0xDD) {
            FAIL("realloc_large_to_small", "data not preserved at offset %d", i);
        }
    }

    walloc_free(p2);
    PASS("realloc_large_to_small");
    return 0;
}

static int test_realloc_grow_large(void) {
    /* grow a large object to an even larger one */
    void *p = walloc_malloc(500);
    if (!p) FAIL("realloc_grow_large", "malloc(500) failed");

    unsigned char *cp = (unsigned char *)p;
    for (int i = 0; i < 500; i++) cp[i] = (unsigned char)(i * 7);

    void *p2 = walloc_realloc(p, 5000);
    if (!p2) FAIL("realloc_grow_large", "realloc to 5000 failed");

    cp = (unsigned char *)p2;
    for (int i = 0; i < 500; i++) {
        unsigned char expected = (unsigned char)(i * 7);
        if (cp[i] != expected) {
            FAIL("realloc_grow_large", "data not preserved at offset %d: got 0x%02x expected 0x%02x",
                 i, cp[i], expected);
        }
    }

    walloc_free(p2);
    PASS("realloc_grow_large");
    return 0;
}

/* deterministic LCG PRNG */
static unsigned int test_rand_state = 12345;
static unsigned int test_rand(void) {
    test_rand_state = test_rand_state * 1103515245 + 12345;
    return (test_rand_state >> 16) & 0x7FFF;
}

static int test_stress(void) {
    #define N_PTRS 200
    #define N_ITERS 5000
    void *ptrs[N_PTRS];
    size_t sizes[N_PTRS];
    memset(ptrs, 0, sizeof(ptrs));
    memset(sizes, 0, sizeof(sizes));

    for (int iter = 0; iter < N_ITERS; iter++) {
        int idx = test_rand() % N_PTRS;
        int action = test_rand() % 3;

        if (action == 0 && !ptrs[idx]) {
            /* malloc */
            size_t sz = (test_rand() % 2000) + 1;
            ptrs[idx] = walloc_malloc(sz);
            if (!ptrs[idx]) FAIL("stress", "malloc(%zu) returned NULL at iter %d", sz, iter);
            sizes[idx] = sz;
            memset(ptrs[idx], (unsigned char)(idx & 0xFF), sz);
        } else if (action == 1 && ptrs[idx]) {
            /* free */
            walloc_free(ptrs[idx]);
            ptrs[idx] = NULL;
            sizes[idx] = 0;
        } else if (action == 2 && ptrs[idx]) {
            /* realloc */
            size_t new_sz = (test_rand() % 2000) + 1;

            /* verify data integrity before realloc */
            unsigned char expected = (unsigned char)(idx & 0xFF);
            unsigned char *cp = (unsigned char *)ptrs[idx];
            size_t check_len = sizes[idx] < 32 ? sizes[idx] : 32;
            for (size_t j = 0; j < check_len; j++) {
                if (cp[j] != expected) {
                    FAIL("stress", "data corruption pre-realloc iter %d idx %d offset %zu: "
                         "got 0x%02x expected 0x%02x", iter, idx, j, cp[j], expected);
                }
            }

            void *new_p = walloc_realloc(ptrs[idx], new_sz);
            if (!new_p) FAIL("stress", "realloc(%zu) returned NULL at iter %d", new_sz, iter);

            /* verify data preserved */
            cp = (unsigned char *)new_p;
            size_t preserved = sizes[idx] < new_sz ? sizes[idx] : new_sz;
            check_len = preserved < 32 ? preserved : 32;
            for (size_t j = 0; j < check_len; j++) {
                if (cp[j] != expected) {
                    FAIL("stress", "data not preserved post-realloc iter %d idx %d offset %zu: "
                         "got 0x%02x expected 0x%02x", iter, idx, j, cp[j], expected);
                }
            }

            ptrs[idx] = new_p;
            sizes[idx] = new_sz;
            memset(ptrs[idx], expected, new_sz);
        }
    }

    /* cleanup */
    for (int i = 0; i < N_PTRS; i++) {
        if (ptrs[i]) walloc_free(ptrs[i]);
    }

    PASS("stress");
    return 0;
}

int main(void) {
    int failures = 0;

    failures += test_init();
    failures += test_basic_malloc();
    failures += test_usable_size_small();
    failures += test_usable_size_large();
    failures += test_usable_size_null();
    failures += test_realloc_null();
    failures += test_realloc_zero();
    failures += test_realloc_grow();
    failures += test_realloc_shrink();
    failures += test_realloc_same_class();
    failures += test_realloc_small_to_large();
    failures += test_realloc_large_to_small();
    failures += test_realloc_grow_large();
    failures += test_stress();

    if (failures > 0) {
        printf("\n%d test(s) FAILED\n", failures);
        return 1;
    }

    printf("\nAll tests PASSED\n");
    return 0;
}
