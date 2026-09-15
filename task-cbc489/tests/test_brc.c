/*
 * test_brc.c - Comprehensive test suite for PEP 703 Biased Reference Counting
 *
 * Compile: gcc -D_GNU_SOURCE -std=gnu11 -O2 -pthread -I/app/include -o test_brc test_brc.c /app/src/brc.c -lpthread
 * Run:     ./test_brc [test_name|all]
 *
 */

#include "brc.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>

/* ================================================================
 * Test infrastructure
 * ================================================================ */

static int g_tests_passed = 0;
static int g_tests_failed = 0;

#define ASSERT_EQ(a, b) do { \
    long long _a = (long long)(a), _b = (long long)(b); \
    if (_a != _b) { \
        fprintf(stderr, "  ASSERT_EQ(%s, %s) FAILED at line %d: got %lld, expected %lld\n", \
                #a, #b, __LINE__, _a, _b); \
        return 1; \
    } \
} while (0)

#define ASSERT_TRUE(cond) do { \
    if (!(cond)) { \
        fprintf(stderr, "  ASSERT_TRUE(%s) FAILED at line %d\n", #cond, __LINE__); \
        return 1; \
    } \
} while (0)

#define ASSERT_FALSE(cond) ASSERT_TRUE(!(cond))

static void noop_dealloc(void *data) { (void)data; }

static BrcStats make_stats(void) {
    BrcStats s;
    atomic_init(&s.alloc_count, 0);
    atomic_init(&s.dealloc_count, 0);
    return s;
}

/* ================================================================
 * Thread helpers
 * ================================================================ */

typedef struct {
    BrcObject *obj;
    int count;
    pthread_barrier_t *barrier;
} StressArgs;

static void *thread_incref(void *arg) {
    StressArgs *a = (StressArgs *)arg;
    if (a->barrier) pthread_barrier_wait(a->barrier);
    for (int i = 0; i < a->count; i++) {
        brc_incref(a->obj);
    }
    return NULL;
}

static void *thread_decref(void *arg) {
    StressArgs *a = (StressArgs *)arg;
    if (a->barrier) pthread_barrier_wait(a->barrier);
    for (int i = 0; i < a->count; i++) {
        brc_decref(a->obj);
    }
    return NULL;
}

static void *thread_incref_decref(void *arg) {
    StressArgs *a = (StressArgs *)arg;
    if (a->barrier) pthread_barrier_wait(a->barrier);
    for (int i = 0; i < a->count; i++) {
        brc_incref(a->obj);
        brc_decref(a->obj);
    }
    return NULL;
}

/* ================================================================
 * Test 1: Basic allocation and deallocation
 * ================================================================ */
static int test_alloc_basic(void) {
    BrcStats stats = make_stats();
    BrcObject *obj = brc_alloc(noop_dealloc, NULL, &stats);
    ASSERT_TRUE(obj != NULL);
    ASSERT_EQ(atomic_load(&stats.alloc_count), 1);
    ASSERT_EQ(brc_get_refcount(obj), 1);
    ASSERT_EQ(brc_get_state(obj), BRC_STATE_DEFAULT);
    ASSERT_FALSE(brc_is_immortal(obj));

    brc_decref(obj);
    ASSERT_EQ(atomic_load(&stats.dealloc_count), 1);
    return 0;
}

/* ================================================================
 * Test 2: Multiple incref/decref from owning thread (local path)
 * ================================================================ */
static int test_incref_decref_owner(void) {
    BrcStats stats = make_stats();
    BrcObject *obj = brc_alloc(noop_dealloc, NULL, &stats);

    for (int i = 0; i < 100; i++) brc_incref(obj);
    ASSERT_EQ(brc_get_refcount(obj), 101);

    for (int i = 0; i < 100; i++) brc_decref(obj);
    ASSERT_EQ(brc_get_refcount(obj), 1);
    ASSERT_EQ(atomic_load(&stats.dealloc_count), 0);

    brc_decref(obj);
    ASSERT_EQ(atomic_load(&stats.dealloc_count), 1);
    return 0;
}

/* ================================================================
 * Test 3: Immortal objects ignore incref/decref
 * ================================================================ */
static int test_immortal(void) {
    BrcStats stats = make_stats();
    BrcObject *obj = brc_alloc(noop_dealloc, NULL, &stats);
    brc_set_immortal(obj);
    ASSERT_TRUE(brc_is_immortal(obj));
    ASSERT_EQ(brc_get_refcount(obj), -1);

    for (int i = 0; i < 100; i++) brc_incref(obj);
    ASSERT_TRUE(brc_is_immortal(obj));
    ASSERT_EQ(brc_get_refcount(obj), -1);

    for (int i = 0; i < 100; i++) brc_decref(obj);
    ASSERT_TRUE(brc_is_immortal(obj));
    ASSERT_EQ(brc_get_refcount(obj), -1);
    ASSERT_EQ(atomic_load(&stats.dealloc_count), 0);
    /* Immortal object intentionally leaked */
    return 0;
}

/* ================================================================
 * Test 4: try_incref on a live object
 * ================================================================ */
static int test_try_incref_live(void) {
    BrcStats stats = make_stats();
    BrcObject *obj = brc_alloc(noop_dealloc, NULL, &stats);

    ASSERT_TRUE(brc_try_incref(obj));
    ASSERT_EQ(brc_get_refcount(obj), 2);

    ASSERT_TRUE(brc_try_incref(obj));
    ASSERT_EQ(brc_get_refcount(obj), 3);

    /* Clean up: owner decref triggers merge, then shared path */
    brc_decref(obj);  /* local 1->0, merge; shared count=2, MERGED */
    brc_decref(obj);  /* shared 2->1 */
    brc_decref(obj);  /* shared 1->0 -> dealloc */
    ASSERT_EQ(atomic_load(&stats.dealloc_count), 1);
    return 0;
}

/* ================================================================
 * Test 5: Cross-thread shared incref
 * ================================================================ */
static int test_shared_incref(void) {
    BrcStats stats = make_stats();
    BrcObject *obj = brc_alloc(noop_dealloc, NULL, &stats);

    pthread_barrier_t barrier;
    pthread_barrier_init(&barrier, NULL, 2);
    StressArgs args = { obj, 5, &barrier };

    pthread_t t;
    pthread_create(&t, NULL, thread_incref, &args);
    pthread_barrier_wait(&barrier);
    pthread_join(t, NULL);

    ASSERT_EQ(brc_get_refcount(obj), 6);

    /* Verify local untouched, shared has the cross-thread refs */
    uint32_t local = atomic_load(&obj->ob_ref_local);
    ASSERT_EQ(local, 1);
    int64_t shared = atomic_load(&obj->ob_ref_shared);
    ASSERT_EQ(shared >> BRC_SHARED_SHIFT, 5);

    /* Owner decref -> merge, then shared decrefs */
    brc_decref(obj);  /* local 1->0, merge -> MERGED, refcount=5 */
    for (int i = 0; i < 4; i++) brc_decref(obj);
    ASSERT_EQ(brc_get_refcount(obj), 1);
    brc_decref(obj);
    ASSERT_EQ(atomic_load(&stats.dealloc_count), 1);

    pthread_barrier_destroy(&barrier);
    return 0;
}

/* ================================================================
 * Test 6: Merge state transition when owner's local reaches zero
 * ================================================================ */
static int test_merge_state(void) {
    BrcStats stats = make_stats();
    BrcObject *obj = brc_alloc(noop_dealloc, NULL, &stats);

    pthread_barrier_t barrier;
    pthread_barrier_init(&barrier, NULL, 2);
    StressArgs args = { obj, 3, &barrier };
    pthread_t t;
    pthread_create(&t, NULL, thread_incref, &args);
    pthread_barrier_wait(&barrier);
    pthread_join(t, NULL);

    ASSERT_EQ(brc_get_refcount(obj), 4);
    ASSERT_EQ(brc_get_state(obj), BRC_STATE_DEFAULT);

    /* Owner decref triggers merge */
    brc_decref(obj);
    ASSERT_EQ(brc_get_state(obj), BRC_STATE_MERGED);
    ASSERT_EQ(brc_get_refcount(obj), 3);
    ASSERT_EQ(atomic_load(&stats.dealloc_count), 0);

    /* Remaining decrefs */
    brc_decref(obj);
    brc_decref(obj);
    ASSERT_EQ(brc_get_refcount(obj), 1);
    brc_decref(obj);
    ASSERT_EQ(atomic_load(&stats.dealloc_count), 1);

    pthread_barrier_destroy(&barrier);
    return 0;
}

/* ================================================================
 * Test 7: Deallocation from MERGED state by a non-owning thread
 * ================================================================ */
static int test_dealloc_merged(void) {
    BrcStats stats = make_stats();
    BrcObject *obj = brc_alloc(noop_dealloc, NULL, &stats);

    /* Non-owning thread increfs once */
    pthread_barrier_t barrier;
    pthread_barrier_init(&barrier, NULL, 2);
    StressArgs args = { obj, 1, &barrier };
    pthread_t t;
    pthread_create(&t, NULL, thread_incref, &args);
    pthread_barrier_wait(&barrier);
    pthread_join(t, NULL);

    /* Owner decref -> merge */
    brc_decref(obj);
    ASSERT_EQ(brc_get_state(obj), BRC_STATE_MERGED);
    ASSERT_EQ(brc_get_refcount(obj), 1);

    /* Non-owning thread decrefs the last reference */
    pthread_barrier_destroy(&barrier);
    pthread_barrier_init(&barrier, NULL, 2);
    args.count = 1;
    args.barrier = &barrier;
    pthread_create(&t, NULL, thread_decref, &args);
    pthread_barrier_wait(&barrier);
    pthread_join(t, NULL);

    ASSERT_EQ(atomic_load(&stats.dealloc_count), 1);

    pthread_barrier_destroy(&barrier);
    return 0;
}

/* ================================================================
 * Test 8: Concurrent shared incref/decref stress
 * ================================================================ */
#define STRESS_THREADS 8
#define STRESS_OPS 10000

static int test_concurrent_shared(void) {
    BrcStats stats = make_stats();
    BrcObject *obj = brc_alloc(noop_dealloc, NULL, &stats);
    brc_incref(obj);  /* local=2 to prevent merge during test */

    pthread_t threads[STRESS_THREADS];
    pthread_barrier_t barrier;

    /* Phase 1: all threads incref STRESS_OPS times */
    pthread_barrier_init(&barrier, NULL, STRESS_THREADS + 1);
    StressArgs args = { obj, STRESS_OPS, &barrier };
    for (int i = 0; i < STRESS_THREADS; i++) {
        pthread_create(&threads[i], NULL, thread_incref, &args);
    }
    pthread_barrier_wait(&barrier);
    for (int i = 0; i < STRESS_THREADS; i++) {
        pthread_join(threads[i], NULL);
    }

    int64_t expected = 2 + (int64_t)STRESS_THREADS * STRESS_OPS;
    ASSERT_EQ(brc_get_refcount(obj), expected);

    /* Phase 2: all threads decref the same amount */
    pthread_barrier_destroy(&barrier);
    pthread_barrier_init(&barrier, NULL, STRESS_THREADS + 1);
    args.barrier = &barrier;
    for (int i = 0; i < STRESS_THREADS; i++) {
        pthread_create(&threads[i], NULL, thread_decref, &args);
    }
    pthread_barrier_wait(&barrier);
    for (int i = 0; i < STRESS_THREADS; i++) {
        pthread_join(threads[i], NULL);
    }

    ASSERT_EQ(brc_get_refcount(obj), 2);
    ASSERT_EQ(atomic_load(&stats.dealloc_count), 0);

    brc_decref(obj);
    brc_decref(obj);
    ASSERT_EQ(atomic_load(&stats.dealloc_count), 1);

    pthread_barrier_destroy(&barrier);
    return 0;
}

/* ================================================================
 * Test 9: Balanced incref/decref pairs from multiple threads
 * ================================================================ */
static int test_concurrent_balanced(void) {
    BrcStats stats = make_stats();
    BrcObject *obj = brc_alloc(noop_dealloc, NULL, &stats);
    brc_incref(obj);  /* local=2 */

    pthread_t threads[STRESS_THREADS];
    pthread_barrier_t barrier;
    pthread_barrier_init(&barrier, NULL, STRESS_THREADS + 1);
    StressArgs args = { obj, STRESS_OPS, &barrier };

    for (int i = 0; i < STRESS_THREADS; i++) {
        pthread_create(&threads[i], NULL, thread_incref_decref, &args);
    }
    pthread_barrier_wait(&barrier);
    for (int i = 0; i < STRESS_THREADS; i++) {
        pthread_join(threads[i], NULL);
    }

    /* Balanced pairs: net change is zero */
    ASSERT_EQ(brc_get_refcount(obj), 2);
    ASSERT_EQ(atomic_load(&stats.dealloc_count), 0);

    brc_decref(obj);
    brc_decref(obj);
    ASSERT_EQ(atomic_load(&stats.dealloc_count), 1);

    pthread_barrier_destroy(&barrier);
    return 0;
}

/* ================================================================
 * Test 10: Full mixed lifecycle
 * ================================================================ */
static int test_full_lifecycle(void) {
    BrcStats stats = make_stats();
    BrcObject *obj = brc_alloc(noop_dealloc, NULL, &stats);

    /* Owner increfs 5 times: local=6 */
    for (int i = 0; i < 5; i++) brc_incref(obj);
    ASSERT_EQ(brc_get_refcount(obj), 6);

    /* 4 non-owning threads each incref 3 times: shared += 12 */
    pthread_barrier_t barrier;
    pthread_barrier_init(&barrier, NULL, 5);
    StressArgs args = { obj, 3, &barrier };
    pthread_t threads[4];
    for (int i = 0; i < 4; i++) {
        pthread_create(&threads[i], NULL, thread_incref, &args);
    }
    pthread_barrier_wait(&barrier);
    for (int i = 0; i < 4; i++) {
        pthread_join(threads[i], NULL);
    }
    ASSERT_EQ(brc_get_refcount(obj), 18);

    /* 4 non-owning threads each decref 2 times: shared -= 8 */
    pthread_barrier_destroy(&barrier);
    pthread_barrier_init(&barrier, NULL, 5);
    args.count = 2;
    args.barrier = &barrier;
    for (int i = 0; i < 4; i++) {
        pthread_create(&threads[i], NULL, thread_decref, &args);
    }
    pthread_barrier_wait(&barrier);
    for (int i = 0; i < 4; i++) {
        pthread_join(threads[i], NULL);
    }
    ASSERT_EQ(brc_get_refcount(obj), 10);  /* local=6 + shared=4 */

    /* Owner decrefs 6 times: local->0, merge. MERGED, refcount=4 */
    for (int i = 0; i < 6; i++) brc_decref(obj);
    ASSERT_EQ(brc_get_state(obj), BRC_STATE_MERGED);
    ASSERT_EQ(brc_get_refcount(obj), 4);
    ASSERT_EQ(atomic_load(&stats.dealloc_count), 0);

    /* Final decrefs via shared path */
    for (int i = 0; i < 3; i++) brc_decref(obj);
    ASSERT_EQ(brc_get_refcount(obj), 1);
    brc_decref(obj);
    ASSERT_EQ(atomic_load(&stats.dealloc_count), 1);

    pthread_barrier_destroy(&barrier);
    return 0;
}

/* ================================================================
 * Main: dispatch by test name
 * ================================================================ */

typedef int (*test_fn)(void);

typedef struct {
    const char *name;
    test_fn fn;
} TestEntry;

static TestEntry all_tests[] = {
    { "alloc_basic",          test_alloc_basic },
    { "incref_decref_owner",  test_incref_decref_owner },
    { "immortal",             test_immortal },
    { "try_incref_live",      test_try_incref_live },
    { "shared_incref",        test_shared_incref },
    { "merge_state",          test_merge_state },
    { "dealloc_merged",       test_dealloc_merged },
    { "concurrent_shared",    test_concurrent_shared },
    { "concurrent_balanced",  test_concurrent_balanced },
    { "full_lifecycle",       test_full_lifecycle },
    { NULL, NULL }
};

int main(int argc, char **argv) {
    if (argc >= 2 && strcmp(argv[1], "all") != 0) {
        for (TestEntry *t = all_tests; t->name; t++) {
            if (strcmp(argv[1], t->name) == 0) {
                return t->fn();
            }
        }
        fprintf(stderr, "Unknown test: %s\nAvailable tests:\n", argv[1]);
        for (TestEntry *t = all_tests; t->name; t++) {
            fprintf(stderr, "  %s\n", t->name);
        }
        return 1;
    }

    printf("Running BRC test suite...\n");
    int failed = 0;
    for (TestEntry *t = all_tests; t->name; t++) {
        printf("  %-30s ", t->name);
        fflush(stdout);
        int result = t->fn();
        if (result == 0) {
            printf("PASS\n");
            g_tests_passed++;
        } else {
            printf("FAIL\n");
            g_tests_failed++;
            failed++;
        }
    }
    printf("\nResults: %d passed, %d failed\n", g_tests_passed, g_tests_failed);
    return failed > 0 ? 1 : 0;
}
