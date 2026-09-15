/*
 * test_stress.c - Multi-round stress test for the GC.
 *
 */
#include "gc.h"
#include <stdio.h>
#include <string.h>

#define HEAP_SIZE (4 * 1024 * 1024)
#define N         128
#define ROUNDS    10

static void *roots[N];
static int   fin_calls    = 0;
static int   fin_data_ok  = 1;

static void stress_fin(void *obj, void *cd) {
    (void)cd;
    fin_calls++;
    if (*(int *)obj != 0xCAFE)
        fin_data_ok = 0;
}

int main(void) {
    int round, i;

    gc_init(HEAP_SIZE);
    gc_add_root(roots, roots + N);

    for (round = 0; round < ROUNDS; round++) {
        /* Allocate N independent objects. */
        for (i = 0; i < N; i++) {
            size_t sz = 64 + (size_t)(i % 10) * 8;
            void *obj = gc_malloc(sz);
            if (!obj) { gc_collect(); obj = gc_malloc(sz); }
            if (!obj) {
                printf("FAIL: alloc round=%d i=%d\n", round, i);
                return 1;
            }
            *(int *)obj = 0xCAFE;
            if (i % 4 == 0)
                gc_register_finalizer(obj, stress_fin, NULL);
            roots[i] = obj;
        }

        /* Drop even-indexed objects (no other object points to them). */
        for (i = 0; i < N; i += 2)
            roots[i] = NULL;

        gc_collect();

        /* Verify surviving objects. */
        for (i = 1; i < N; i += 2) {
            if (!roots[i] || *(int *)roots[i] != 0xCAFE) {
                printf("FAIL: live object corrupted round=%d slot=%d\n",
                       round, i);
                return 1;
            }
        }
    }

    /* Drop everything, final collection. */
    for (i = 0; i < N; i++) roots[i] = NULL;
    gc_collect();

    if (!fin_data_ok) {
        printf("FAIL: finalizer saw corrupt data\n");
        return 1;
    }
    if (fin_calls == 0) {
        printf("FAIL: no finalizers called in stress test\n");
        return 1;
    }

    printf("PASS (rounds=%d, fin_calls=%d)\n", ROUNDS, fin_calls);
    gc_shutdown();
    return 0;
}
