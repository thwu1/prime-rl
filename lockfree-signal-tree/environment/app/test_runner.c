/*
 * test_runner.c — Comprehensive tests for the signal tree implementation.
 *
 * Build:  make
 * Run:    ./test_runner
 *
 * Prints PASS/FAIL for each test and exits 0 on all-pass, 1 on any failure.
 *
 */

#include "signal_tree.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <stdatomic.h>

static int g_failures = 0;
static int g_passes   = 0;

#define ASSERT(cond, msg) do {                                              \
    if (!(cond)) {                                                          \
        printf("FAIL: %s: %s (line %d)\n", test_name, (msg), __LINE__);    \
        return 1;                                                           \
    }                                                                       \
} while (0)

#define PASS() do {                      \
    printf("PASS: %s\n", test_name);     \
    return 0;                            \
} while (0)

/* ----------------------------------------------------------------------- */
/* Test 1: Create and destroy without crashing                              */
/* ----------------------------------------------------------------------- */
static int test_create_destroy(void) {
    const char *test_name = "test_create_destroy";
    signal_tree_t *tree = signal_tree_create();
    ASSERT(tree != NULL, "signal_tree_create returned NULL");
    signal_tree_destroy(tree);
    PASS();
}

/* ----------------------------------------------------------------------- */
/* Test 2: A new tree is empty                                              */
/* ----------------------------------------------------------------------- */
static int test_empty_initially(void) {
    const char *test_name = "test_empty_initially";
    signal_tree_t *tree = signal_tree_create();
    ASSERT(signal_tree_empty(tree), "new tree should be empty");
    signal_tree_destroy(tree);
    PASS();
}

/* ----------------------------------------------------------------------- */
/* Test 3: Set a single signal and select it back                           */
/* ----------------------------------------------------------------------- */
static int test_set_single(void) {
    const char *test_name = "test_set_single";
    signal_tree_t *tree = signal_tree_create();

    st_set_result_t sr = signal_tree_set(tree, 0);
    ASSERT(sr.tree_was_empty,  "first set: tree should have been empty");
    ASSERT(sr.signal_was_new,  "first set: signal should be new");
    ASSERT(!signal_tree_empty(tree), "tree should not be empty after set");

    st_select_result_t sel = signal_tree_select(tree, 0);
    ASSERT(sel.index == 0,       "select should return index 0");
    ASSERT(sel.tree_is_empty,    "tree should be empty after last select");
    ASSERT(signal_tree_empty(tree), "tree should now be empty");

    signal_tree_destroy(tree);
    PASS();
}

/* ----------------------------------------------------------------------- */
/* Test 4: Set all 512, select all 512, full coverage                       */
/* ----------------------------------------------------------------------- */
static int test_set_all_select_all(void) {
    const char *test_name = "test_set_all_select_all";
    signal_tree_t *tree = signal_tree_create();

    for (uint64_t i = 0; i < ST_CAPACITY; i++) {
        st_set_result_t sr = signal_tree_set(tree, i);
        ASSERT(sr.signal_was_new, "each signal should be new");
        if (i == 0) ASSERT(sr.tree_was_empty, "first set should see empty tree");
    }
    ASSERT(!signal_tree_empty(tree), "tree should not be empty after setting all");

    int seen[ST_CAPACITY];
    memset(seen, 0, sizeof(seen));

    for (uint64_t i = 0; i < ST_CAPACITY; i++) {
        st_select_result_t sel = signal_tree_select(tree, i);
        ASSERT(sel.index != ST_INVALID_INDEX, "select should succeed");
        ASSERT(sel.index < ST_CAPACITY,       "index should be in range");
        ASSERT(!seen[sel.index],              "no duplicate selects");
        seen[sel.index] = 1;
    }
    ASSERT(signal_tree_empty(tree), "tree should be empty after selecting all");

    for (uint64_t i = 0; i < ST_CAPACITY; i++)
        ASSERT(seen[i], "all signals must have been selected");

    signal_tree_destroy(tree);
    PASS();
}

/* ----------------------------------------------------------------------- */
/* Test 5: Double-set should not double-count                               */
/* ----------------------------------------------------------------------- */
static int test_double_set(void) {
    const char *test_name = "test_double_set";
    signal_tree_t *tree = signal_tree_create();

    st_set_result_t sr1 = signal_tree_set(tree, 42);
    ASSERT(sr1.signal_was_new, "first set should be new");

    st_set_result_t sr2 = signal_tree_set(tree, 42);
    ASSERT(!sr2.signal_was_new, "second set of same signal should not be new");

    st_select_result_t sel = signal_tree_select(tree, 0);
    ASSERT(sel.index == 42,     "select should return 42");
    ASSERT(sel.tree_is_empty,   "tree should be empty after selecting only signal");

    st_select_result_t sel2 = signal_tree_select(tree, 0);
    ASSERT(sel2.index == ST_INVALID_INDEX, "second select should find nothing");

    signal_tree_destroy(tree);
    PASS();
}

/* ----------------------------------------------------------------------- */
/* Test 6: Select from empty tree                                           */
/* ----------------------------------------------------------------------- */
static int test_select_empty(void) {
    const char *test_name = "test_select_empty";
    signal_tree_t *tree = signal_tree_create();

    st_select_result_t sel = signal_tree_select(tree, 0);
    ASSERT(sel.index == ST_INVALID_INDEX, "select from empty should return INVALID");

    signal_tree_destroy(tree);
    PASS();
}

/* ----------------------------------------------------------------------- */
/* Test 7: tree_was_empty return value                                      */
/* ----------------------------------------------------------------------- */
static int test_tree_was_empty(void) {
    const char *test_name = "test_tree_was_empty";
    signal_tree_t *tree = signal_tree_create();

    st_set_result_t sr1 = signal_tree_set(tree, 100);
    ASSERT(sr1.tree_was_empty, "first set on empty tree: tree_was_empty should be true");

    st_set_result_t sr2 = signal_tree_set(tree, 200);
    ASSERT(!sr2.tree_was_empty, "second set: tree_was_empty should be false");

    signal_tree_destroy(tree);
    PASS();
}

/* ----------------------------------------------------------------------- */
/* Test 8: Even-index only set-then-select                                  */
/* ----------------------------------------------------------------------- */
static int test_interleaved(void) {
    const char *test_name = "test_interleaved";
    signal_tree_t *tree = signal_tree_create();

    int num_set = 0;
    for (uint64_t i = 0; i < ST_CAPACITY; i += 2) {
        signal_tree_set(tree, i);
        num_set++;
    }

    int seen[ST_CAPACITY];
    memset(seen, 0, sizeof(seen));
    for (int i = 0; i < num_set; i++) {
        st_select_result_t sel = signal_tree_select(tree, (uint64_t)i);
        ASSERT(sel.index != ST_INVALID_INDEX, "select should succeed");
        ASSERT(sel.index < ST_CAPACITY,       "index in range");
        ASSERT(sel.index % 2 == 0,            "selected index should be even");
        ASSERT(!seen[sel.index],              "no duplicates");
        seen[sel.index] = 1;
    }
    ASSERT(signal_tree_empty(tree), "tree should be empty");

    signal_tree_destroy(tree);
    PASS();
}

/* ----------------------------------------------------------------------- */
/* Test 9: Leaf-boundary signals                                            */
/* ----------------------------------------------------------------------- */
static int test_boundary_signals(void) {
    const char *test_name = "test_boundary_signals";
    signal_tree_t *tree = signal_tree_create();

    uint64_t boundaries[] = {0,63, 64,127, 128,191, 192,255,
                             256,319, 320,383, 384,447, 448,511};
    int nb = (int)(sizeof(boundaries)/sizeof(boundaries[0]));

    for (int i = 0; i < nb; i++)
        signal_tree_set(tree, boundaries[i]);

    int seen[ST_CAPACITY];
    memset(seen, 0, sizeof(seen));
    for (int i = 0; i < nb; i++) {
        st_select_result_t sel = signal_tree_select(tree, (uint64_t)i);
        ASSERT(sel.index != ST_INVALID_INDEX, "select should succeed");
        seen[sel.index] = 1;
    }
    for (int i = 0; i < nb; i++)
        ASSERT(seen[boundaries[i]], "boundary signal must be selected");
    ASSERT(signal_tree_empty(tree), "tree should be empty");

    signal_tree_destroy(tree);
    PASS();
}

/* ----------------------------------------------------------------------- */
/* Test 10: Prime-indexed signals                                           */
/* ----------------------------------------------------------------------- */
static int test_specific_pattern(void) {
    const char *test_name = "test_specific_pattern";
    signal_tree_t *tree = signal_tree_create();

    /* All primes < 512 */
    uint64_t primes[] = {
        2,3,5,7,11,13,17,19,23,29,31,37,41,43,47,53,59,61,67,71,73,79,83,89,
        97,101,103,107,109,113,127,131,137,139,149,151,157,163,167,173,179,181,
        191,193,197,199,211,223,227,229,233,239,241,251,257,263,269,271,277,281,
        283,293,307,311,313,317,331,337,347,349,353,359,367,373,379,383,389,397,
        401,409,419,421,431,433,439,443,449,457,461,463,467,479,487,491,499,503,
        509
    };
    int np = (int)(sizeof(primes)/sizeof(primes[0]));

    for (int i = 0; i < np; i++)
        signal_tree_set(tree, primes[i]);

    int seen[ST_CAPACITY];
    memset(seen, 0, sizeof(seen));
    int count = 0;
    while (!signal_tree_empty(tree)) {
        st_select_result_t sel = signal_tree_select(tree, (uint64_t)count);
        ASSERT(sel.index != ST_INVALID_INDEX, "select should succeed when not empty");
        ASSERT(!seen[sel.index], "no duplicates");
        seen[sel.index] = 1;
        count++;
        ASSERT(count <= np + 1, "too many selects — possible infinite loop");
    }
    ASSERT(count == np, "should select exactly the number of primes");
    for (int i = 0; i < np; i++)
        ASSERT(seen[primes[i]], "each prime signal must be selected");

    signal_tree_destroy(tree);
    PASS();
}

/* ----------------------------------------------------------------------- */
/* Test 11: Concurrent set + select (4 threads, partitioned)                */
/* ----------------------------------------------------------------------- */
typedef struct {
    signal_tree_t    *tree;
    int               thread_id;
    int               num_threads;
    uint64_t         *selected_buf;
    int               selected_count;
    pthread_barrier_t *barrier;
} conc_data_t;

static void *concurrent_worker(void *arg) {
    conc_data_t *d = (conc_data_t *)arg;
    int sigs_per = ST_CAPACITY / d->num_threads;   /* 128 */
    int base     = d->thread_id * sigs_per;

    /* Phase 1 — set own range */
    for (int i = 0; i < sigs_per; i++)
        signal_tree_set(d->tree, (uint64_t)(base + i));

    pthread_barrier_wait(d->barrier);

    /* Phase 2 — select globally */
    d->selected_count = 0;
    for (int i = 0; i < sigs_per; i++) {
        st_select_result_t sel = signal_tree_select(
                d->tree, (uint64_t)(d->thread_id * 7919 + i));
        if (sel.index != ST_INVALID_INDEX)
            d->selected_buf[d->selected_count++] = sel.index;
    }
    return NULL;
}

static int test_concurrent(void) {
    const char *test_name = "test_concurrent";
    signal_tree_t *tree = signal_tree_create();
    enum { NT = 4 };

    pthread_t       thr[NT];
    conc_data_t     td[NT];
    uint64_t        bufs[NT][ST_CAPACITY];
    pthread_barrier_t bar;
    pthread_barrier_init(&bar, NULL, NT);

    for (int i = 0; i < NT; i++) {
        td[i] = (conc_data_t){tree, i, NT, bufs[i], 0, &bar};
        pthread_create(&thr[i], NULL, concurrent_worker, &td[i]);
    }
    for (int i = 0; i < NT; i++)
        pthread_join(thr[i], NULL);

    int coverage[ST_CAPACITY];
    memset(coverage, 0, sizeof(coverage));
    int total = 0;
    for (int i = 0; i < NT; i++) {
        total += td[i].selected_count;
        for (int j = 0; j < td[i].selected_count; j++) {
            uint64_t idx = td[i].selected_buf[j];
            ASSERT(idx < ST_CAPACITY, "index in range");
            ASSERT(!coverage[idx],    "no duplicate across threads");
            coverage[idx] = 1;
        }
    }

    /* Drain any remaining signals */
    int remaining = 0;
    for (;;) {
        st_select_result_t sel = signal_tree_select(tree, (uint64_t)remaining);
        if (sel.index == ST_INVALID_INDEX) break;
        ASSERT(!coverage[sel.index], "remaining signal not already selected");
        coverage[sel.index] = 1;
        total++;
        remaining++;
    }
    ASSERT(total == ST_CAPACITY, "total selected must equal capacity");
    for (int i = 0; i < ST_CAPACITY; i++)
        ASSERT(coverage[i], "every signal accounted for");

    pthread_barrier_destroy(&bar);
    signal_tree_destroy(tree);
    PASS();
}

/* ----------------------------------------------------------------------- */
/* Test 12: Stress — interleaved set/select across 4 threads                */
/* ----------------------------------------------------------------------- */
static atomic_uint_fast64_t g_stress_new_sets   = 0;
static atomic_uint_fast64_t g_stress_selects    = 0;

typedef struct {
    signal_tree_t     *tree;
    int                thread_id;
    int                iterations;
    pthread_barrier_t *barrier;
} stress_data_t;

static void *stress_worker(void *arg) {
    stress_data_t *d = (stress_data_t *)arg;
    int tid  = d->thread_id;
    int sigs = ST_CAPACITY / 4;   /* 128 per thread */
    uint64_t local_new = 0, local_sel = 0;

    pthread_barrier_wait(d->barrier);

    for (int i = 0; i < d->iterations; i++) {
        uint64_t sig = (uint64_t)(tid * sigs + (i % sigs));
        st_set_result_t sr = signal_tree_set(d->tree, sig);
        if (sr.signal_was_new) local_new++;

        st_select_result_t sel = signal_tree_select(
                d->tree, (uint64_t)(tid * 104729 + i));
        if (sel.index != ST_INVALID_INDEX) local_sel++;
    }
    atomic_fetch_add(&g_stress_new_sets, local_new);
    atomic_fetch_add(&g_stress_selects,  local_sel);
    return NULL;
}

static int test_stress(void) {
    const char *test_name = "test_stress";
    signal_tree_t *tree = signal_tree_create();
    enum { NT = 4, ITERS = 5000 };

    atomic_store(&g_stress_new_sets, 0);
    atomic_store(&g_stress_selects,  0);

    pthread_t       thr[NT];
    stress_data_t   sd[NT];
    pthread_barrier_t bar;
    pthread_barrier_init(&bar, NULL, NT);

    for (int i = 0; i < NT; i++) {
        sd[i] = (stress_data_t){tree, i, ITERS, &bar};
        pthread_create(&thr[i], NULL, stress_worker, &sd[i]);
    }
    for (int i = 0; i < NT; i++)
        pthread_join(thr[i], NULL);

    /* Drain remaining */
    uint64_t drained = 0;
    for (;;) {
        st_select_result_t sel = signal_tree_select(tree, drained);
        if (sel.index == ST_INVALID_INDEX) break;
        drained++;
    }

    uint64_t total_new = atomic_load(&g_stress_new_sets);
    uint64_t total_sel = atomic_load(&g_stress_selects) + drained;

    ASSERT(total_new == total_sel,
           "newly-set count must equal selected + drained");
    ASSERT(signal_tree_empty(tree), "tree must be empty after drain");

    pthread_barrier_destroy(&bar);
    signal_tree_destroy(tree);
    PASS();
}

/* ----------------------------------------------------------------------- */
/* Main                                                                     */
/* ----------------------------------------------------------------------- */
int main(void) {
    int (*tests[])(void) = {
        test_create_destroy,
        test_empty_initially,
        test_set_single,
        test_set_all_select_all,
        test_double_set,
        test_select_empty,
        test_tree_was_empty,
        test_interleaved,
        test_boundary_signals,
        test_specific_pattern,
        test_concurrent,
        test_stress,
    };
    int n = (int)(sizeof(tests) / sizeof(tests[0]));

    for (int i = 0; i < n; i++) {
        if (tests[i]()) g_failures++;
        else            g_passes++;
    }

    printf("\n%d/%d tests passed\n", g_passes, g_passes + g_failures);
    return g_failures > 0 ? 1 : 0;
}
