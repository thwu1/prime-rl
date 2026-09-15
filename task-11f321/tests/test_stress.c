/*
 * test_stress.c — Stress tests: sustained allocation, memory
 *                 reclamation, and mixed object graphs.
 *
 */
#include "gc.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int tests_passed = 0;
static int tests_failed = 0;

#define TEST(name) do { printf("  TEST: %s ... ", name); fflush(stdout); } while (0)
#define PASS()     do { printf("PASS\n"); tests_passed++; } while (0)
#define FAIL(msg)  do { printf("FAIL: %s\n", msg); tests_failed++; return; } while (0)
#define CHECK(c, m) do { if (!(c)) { FAIL(m); } } while (0)

/* ================================================================
 * 1. Sustained allocation under a tight heap
 *    Only the last pair is rooted; GC must reclaim the rest.
 * ================================================================ */
static void test_sustained_allocation(void) {
    TEST("sustained allocation (100K pairs, 256KB heap)");
    gc_heap_t *h = gc_heap_create(256 * 1024); /* 256 KB */

    gc_obj_t *root = NULL;
    gc_root_push(h, &root);

    for (int i = 0; i < 100000; i++) {
        gc_pair_t *p = gc_alloc_pair(h);
        CHECK(p != NULL, "OOM — GC did not reclaim enough memory");
        root = (gc_obj_t *)p;
    }

    gc_collect(h);
    gc_stats_t s = gc_get_stats(h);
    CHECK(s.live_object_count == 1, "expected 1 live object");

    gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ================================================================
 * 2. Growing linked list (tests graph tracing at scale)
 * ================================================================ */
static void test_growing_list(void) {
    TEST("growing linked list (1000 elements)");
    gc_heap_t *h = gc_heap_create(0);

    gc_obj_t *root = NULL;
    gc_root_push(h, &root);

    for (int i = 0; i < 1000; i++) {
        gc_pair_t *p = gc_alloc_pair(h);
        CHECK(p != NULL, "OOM");
        p->cdr = root;
        root = (gc_obj_t *)p;
    }

    /* sprinkle garbage */
    for (int i = 0; i < 2000; i++)
        gc_alloc_pair(h);

    gc_collect(h);
    gc_stats_t s = gc_get_stats(h);
    CHECK(s.live_object_count == 1000, "expected 1000-element list");

    /* walk the list */
    gc_obj_t *cur = root;
    int count = 0;
    while (cur != NULL) {
        CHECK(cur->type == GC_TYPE_PAIR, "type corrupted in list");
        cur = ((gc_pair_t *)cur)->cdr;
        count++;
        CHECK(count <= 1001, "infinite loop in list walk");
    }
    CHECK(count == 1000, "list length mismatch");

    gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ================================================================
 * 3. Mixed object types
 * ================================================================ */
static void test_mixed_types(void) {
    TEST("mixed object types under GC pressure");
    gc_heap_t *h = gc_heap_create(512 * 1024);

    gc_obj_t *root = NULL;
    gc_root_push(h, &root);

    for (int i = 0; i < 10000; i++) {
        switch (i % 4) {
        case 0: {
            gc_pair_t *p = gc_alloc_pair(h);
            CHECK(p != NULL, "OOM (pair)");
            root = (gc_obj_t *)p;
            break;
        }
        case 1: {
            gc_vector_t *v = gc_alloc_vector(h, 4);
            CHECK(v != NULL, "OOM (vector)");
            root = (gc_obj_t *)v;
            break;
        }
        case 2: {
            gc_opaque_t *o = gc_alloc_opaque(h, 32);
            CHECK(o != NULL, "OOM (opaque)");
            root = (gc_obj_t *)o;
            break;
        }
        case 3: {
            gc_pair_t *k = gc_alloc_pair(h);
            CHECK(k != NULL, "OOM (eph key)");
            gc_obj_t *kr = (gc_obj_t *)k;
            gc_root_push(h, &kr);
            gc_ephemeron_t *e = gc_alloc_ephemeron(h, kr, root);
            CHECK(e != NULL, "OOM (ephemeron)");
            gc_root_pop(h);
            root = (gc_obj_t *)e;
            break;
        }
        }
    }

    gc_collect(h);
    gc_stats_t s = gc_get_stats(h);
    CHECK(s.live_object_count >= 1, "at least 1 live object");

    gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ================================================================
 * 4. Ephemerons under churn: create many, collect, verify broken
 * ================================================================ */
static void test_ephemeron_churn(void) {
    TEST("ephemeron churn (1000 ephemerons, all break)");
    gc_heap_t *h = gc_heap_create(0);

    gc_obj_t *eph_root = NULL;
    gc_root_push(h, &eph_root);

    /* Create 1000 ephemerons whose keys have no external root.
       Keep only the ephemerons alive via a linked list of pairs. */
    gc_obj_t *list = NULL;
    gc_obj_t *tmp = NULL;
    gc_root_push(h, &list);
    gc_root_push(h, &tmp);

    for (int i = 0; i < 1000; i++) {
        gc_pair_t *key = gc_alloc_pair(h);
        tmp = (gc_obj_t *)key;
        gc_ephemeron_t *e = gc_alloc_ephemeron(h, tmp, tmp);
        tmp = (gc_obj_t *)e;

        gc_pair_t *node = gc_alloc_pair(h);
        node->car = tmp;
        node->cdr = list;
        list = (gc_obj_t *)node;
        tmp = NULL;
    }

    gc_collect(h);

    gc_stats_t s = gc_get_stats(h);
    /* 1000 list nodes + 1000 ephemerons (broken) = 2000 */
    CHECK(s.live_object_count == 2000, "expected 2000 live objects");
    CHECK(s.broken_ephemeron_count == 1000, "all 1000 should be broken");

    gc_root_pop(h); gc_root_pop(h); gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ================================================================
 * 5. Repeated collect on empty heap (idempotent)
 * ================================================================ */
static void test_repeated_empty_collect(void) {
    TEST("repeated collect on empty heap");
    gc_heap_t *h = gc_heap_create(0);

    for (int i = 0; i < 50; i++)
        gc_collect(h);

    gc_stats_t s = gc_get_stats(h);
    CHECK(s.collection_count == 50, "50 collections");
    CHECK(s.live_object_count == 0, "0 live objects");

    gc_heap_destroy(h);
    PASS();
}

/* ================================================================
 * 6. Large vectors
 * ================================================================ */
static void test_large_vectors(void) {
    TEST("large vector (500 slots)");
    gc_heap_t *h = gc_heap_create(0);
    gc_obj_t *root = NULL;
    gc_root_push(h, &root);

    gc_vector_t *v = gc_alloc_vector(h, 500);
    CHECK(v != NULL, "OOM on large vector");
    root = (gc_obj_t *)v;

    for (int i = 0; i < 500; i++) {
        gc_pair_t *p = gc_alloc_pair(h);
        CHECK(p != NULL, "OOM filling vector");
        v = (gc_vector_t *)root;
        v->data[i] = (gc_obj_t *)p;
    }

    /* garbage */
    for (int i = 0; i < 500; i++)
        gc_alloc_pair(h);

    gc_collect(h);

    gc_stats_t s = gc_get_stats(h);
    CHECK(s.live_object_count == 501, "501 objects (1 vector + 500 pairs)");

    gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ================================================================
 * 7. Heap capacity enforcement
 * ================================================================ */
static void test_heap_capacity(void) {
    TEST("heap capacity returns NULL on OOM");
    /* Very small heap: only a handful of objects fit. */
    gc_heap_t *h = gc_heap_create(512);

    gc_obj_t *r1 = NULL, *r2 = NULL;
    gc_root_push(h, &r1);
    gc_root_push(h, &r2);

    /* Allocate two rooted pairs so they can't be freed */
    gc_pair_t *p1 = gc_alloc_pair(h);
    if (p1) r1 = (gc_obj_t *)p1;
    gc_pair_t *p2 = gc_alloc_pair(h);
    if (p2) r2 = (gc_obj_t *)p2;

    /* Keep allocating rooted objects; eventually must get NULL */
    int got_null = 0;
    gc_obj_t *extras[200];
    int extra_count = 0;
    for (int i = 0; i < 200; i++) {
        gc_pair_t *p = gc_alloc_pair(h);
        if (p == NULL) { got_null = 1; break; }
        extras[extra_count] = (gc_obj_t *)p;
        gc_root_push(h, &extras[extra_count]);
        extra_count++;
    }

    CHECK(got_null, "heap should have returned NULL at some point");

    for (int i = 0; i < extra_count; i++) gc_root_pop(h);
    gc_root_pop(h); gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

int main(void) {
    printf("=== Stress Tests ===\n");
    test_sustained_allocation();
    test_growing_list();
    test_mixed_types();
    test_ephemeron_churn();
    test_repeated_empty_collect();
    test_large_vectors();
    test_heap_capacity();

    printf("\nResults: %d passed, %d failed\n", tests_passed, tests_failed);
    if (tests_failed == 0) {
        printf("ALL TESTS PASSED\n");
        return 0;
    }
    return 1;
}
