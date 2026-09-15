/*
 * test_basic.c — Tests basic GC allocation, root management, and collection.
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

/* ---- heap create / destroy ---- */
static void test_create_destroy(void) {
    TEST("heap create and destroy");
    gc_heap_t *h = gc_heap_create(0);
    CHECK(h != NULL, "gc_heap_create returned NULL");
    gc_heap_destroy(h);
    PASS();
}

/* ---- allocate each type ---- */
static void test_alloc_pair(void) {
    TEST("allocate pair");
    gc_heap_t *h = gc_heap_create(0);
    gc_obj_t *r = NULL;
    gc_root_push(h, &r);

    gc_pair_t *p = gc_alloc_pair(h);
    r = (gc_obj_t *)p;
    CHECK(p != NULL,                "returned NULL");
    CHECK(p->hdr.type == GC_TYPE_PAIR, "wrong type tag");
    CHECK(p->car == NULL,           "car not NULL-initialized");
    CHECK(p->cdr == NULL,           "cdr not NULL-initialized");

    gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

static void test_alloc_vector(void) {
    TEST("allocate vector");
    gc_heap_t *h = gc_heap_create(0);
    gc_obj_t *r = NULL;
    gc_root_push(h, &r);

    gc_vector_t *v = gc_alloc_vector(h, 10);
    r = (gc_obj_t *)v;
    CHECK(v != NULL,                  "returned NULL");
    CHECK(v->hdr.type == GC_TYPE_VECTOR, "wrong type tag");
    CHECK(v->length == 10,           "wrong length");
    for (size_t i = 0; i < 10; i++)
        CHECK(v->data[i] == NULL, "slot not NULL-initialized");

    gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

static void test_alloc_opaque(void) {
    TEST("allocate opaque");
    gc_heap_t *h = gc_heap_create(0);
    gc_obj_t *r = NULL;
    gc_root_push(h, &r);

    gc_opaque_t *o = gc_alloc_opaque(h, 100);
    r = (gc_obj_t *)o;
    CHECK(o != NULL,                  "returned NULL");
    CHECK(o->hdr.type == GC_TYPE_OPAQUE, "wrong type tag");
    CHECK(o->length == 100,          "wrong length");
    for (size_t i = 0; i < 100; i++)
        CHECK(o->data[i] == 0, "byte not zero-initialized");

    gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

static void test_alloc_ephemeron(void) {
    TEST("allocate ephemeron");
    gc_heap_t *h = gc_heap_create(0);
    gc_obj_t *r1 = NULL, *r2 = NULL;
    gc_root_push(h, &r1);
    gc_root_push(h, &r2);

    gc_pair_t *k = gc_alloc_pair(h);
    r1 = (gc_obj_t *)k;
    gc_pair_t *v = gc_alloc_pair(h);
    r2 = (gc_obj_t *)v;

    gc_ephemeron_t *e = gc_alloc_ephemeron(h, r1, r2);
    CHECK(e != NULL,                      "returned NULL");
    CHECK(e->hdr.type == GC_TYPE_EPHEMERON, "wrong type tag");
    CHECK(e->key   == r1,                 "key mismatch");
    CHECK(e->value == r2,                 "value mismatch");

    gc_root_pop(h);
    gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ---- collection: no roots → everything freed ---- */
static void test_collect_all_garbage(void) {
    TEST("collect all garbage");
    gc_heap_t *h = gc_heap_create(0);

    for (int i = 0; i < 200; i++)
        gc_alloc_pair(h);

    gc_collect(h);
    gc_stats_t s = gc_get_stats(h);
    CHECK(s.live_object_count == 0,
          "expected 0 live objects after collecting unreachable garbage");

    gc_heap_destroy(h);
    PASS();
}

/* ---- collection: rooted object survives ---- */
static void test_collect_preserves_root(void) {
    TEST("collection preserves rooted object");
    gc_heap_t *h = gc_heap_create(0);
    gc_obj_t *root = NULL;
    gc_root_push(h, &root);

    gc_pair_t *p = gc_alloc_pair(h);
    root = (gc_obj_t *)p;

    /* create garbage */
    for (int i = 0; i < 200; i++)
        gc_alloc_pair(h);

    gc_collect(h);
    CHECK(root != NULL,                "root cleared");
    CHECK(root->type == GC_TYPE_PAIR, "type corrupted");

    gc_stats_t s = gc_get_stats(h);
    CHECK(s.live_object_count == 1, "expected exactly 1 live object");

    gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ---- collection traces object graph ---- */
static void test_collect_traces_graph(void) {
    TEST("collection traces linked object graph");
    gc_heap_t *h = gc_heap_create(0);

    gc_obj_t *root = NULL, *t1 = NULL, *t2 = NULL;
    gc_root_push(h, &root);
    gc_root_push(h, &t1);
    gc_root_push(h, &t2);

    /* build a 3-element linked list: p1 -> p2 -> p3 */
    gc_pair_t *p3 = gc_alloc_pair(h);
    t2 = (gc_obj_t *)p3;
    gc_pair_t *p2 = gc_alloc_pair(h);
    t1 = (gc_obj_t *)p2;
    p2->cdr = t2;
    gc_pair_t *p1 = gc_alloc_pair(h);
    root = (gc_obj_t *)p1;
    p1->cdr = t1;

    gc_root_pop(h); /* t2 */
    gc_root_pop(h); /* t1 */

    /* create garbage */
    for (int i = 0; i < 200; i++)
        gc_alloc_pair(h);

    gc_collect(h);

    gc_stats_t s = gc_get_stats(h);
    CHECK(s.live_object_count == 3,
          "expected 3 live objects in the chain");

    /* verify chain integrity */
    gc_pair_t *head = (gc_pair_t *)root;
    CHECK(head->cdr != NULL, "p1->cdr is NULL");
    gc_pair_t *mid = (gc_pair_t *)head->cdr;
    CHECK(mid->cdr != NULL,  "p2->cdr is NULL");

    gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ---- collection frees memory ---- */
static void test_collect_frees_memory(void) {
    TEST("collection frees memory");
    gc_heap_t *h = gc_heap_create(0);
    gc_obj_t *root = NULL;
    gc_root_push(h, &root);

    for (int i = 0; i < 500; i++) {
        gc_pair_t *p = gc_alloc_pair(h);
        CHECK(p != NULL, "OOM during allocation");
        root = (gc_obj_t *)p;
    }

    gc_collect(h);
    gc_stats_t s = gc_get_stats(h);
    CHECK(s.live_object_count == 1, "expected 1 live object");
    CHECK(s.total_freed > 0,       "total_freed should be > 0");

    gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ---- vector references are traced ---- */
static void test_vector_references(void) {
    TEST("vector references traced");
    gc_heap_t *h = gc_heap_create(0);
    gc_obj_t *root = NULL;
    gc_root_push(h, &root);

    gc_vector_t *v = gc_alloc_vector(h, 5);
    root = (gc_obj_t *)v;

    for (int i = 0; i < 5; i++) {
        gc_pair_t *p = gc_alloc_pair(h);
        v = (gc_vector_t *)root;  /* re-read through root (non-moving, but good practice) */
        v->data[i] = (gc_obj_t *)p;
    }

    for (int i = 0; i < 100; i++)
        gc_alloc_pair(h);

    gc_collect(h);

    gc_stats_t s = gc_get_stats(h);
    CHECK(s.live_object_count == 6,
          "expected 6 live objects (1 vector + 5 pairs)");

    gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ---- multiple independent roots ---- */
static void test_multiple_roots(void) {
    TEST("multiple independent roots");
    gc_heap_t *h = gc_heap_create(0);
    gc_obj_t *r1 = NULL, *r2 = NULL, *r3 = NULL;
    gc_root_push(h, &r1);
    gc_root_push(h, &r2);
    gc_root_push(h, &r3);

    r1 = (gc_obj_t *)gc_alloc_pair(h);
    r2 = (gc_obj_t *)gc_alloc_vector(h, 3);
    r3 = (gc_obj_t *)gc_alloc_opaque(h, 16);

    for (int i = 0; i < 100; i++)
        gc_alloc_pair(h);

    gc_collect(h);

    gc_stats_t s = gc_get_stats(h);
    CHECK(s.live_object_count == 3, "expected 3 live objects");

    gc_root_pop(h);
    gc_root_pop(h);
    gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ---- root pop removes reference ---- */
static void test_root_pop(void) {
    TEST("root pop removes reference");
    gc_heap_t *h = gc_heap_create(0);
    gc_obj_t *r1 = NULL, *r2 = NULL;
    gc_root_push(h, &r1);
    gc_root_push(h, &r2);

    r1 = (gc_obj_t *)gc_alloc_pair(h);
    r2 = (gc_obj_t *)gc_alloc_pair(h);

    gc_root_pop(h); /* remove r2 */

    gc_collect(h);

    gc_stats_t s = gc_get_stats(h);
    CHECK(s.live_object_count == 1,
          "expected 1 live object after popping one root");

    gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ---- stats collection_count increments ---- */
static void test_stats_collection_count(void) {
    TEST("stats collection_count");
    gc_heap_t *h = gc_heap_create(0);

    gc_stats_t s0 = gc_get_stats(h);
    CHECK(s0.collection_count == 0, "initial count should be 0");

    gc_collect(h);
    gc_stats_t s1 = gc_get_stats(h);
    CHECK(s1.collection_count == 1, "should be 1 after one collect");

    gc_collect(h);
    gc_collect(h);
    gc_stats_t s3 = gc_get_stats(h);
    CHECK(s3.collection_count == 3, "should be 3 after three collects");

    gc_heap_destroy(h);
    PASS();
}

/* ---- cyclic graph does not crash ---- */
static void test_cyclic_graph(void) {
    TEST("cyclic object graph");
    gc_heap_t *h = gc_heap_create(0);
    gc_obj_t *root = NULL;
    gc_root_push(h, &root);

    gc_pair_t *a = gc_alloc_pair(h);
    root = (gc_obj_t *)a;
    gc_pair_t *b = gc_alloc_pair(h);
    a = (gc_pair_t *)root;
    a->car = (gc_obj_t *)b;
    b->car = root;  /* cycle: a -> b -> a */

    for (int i = 0; i < 100; i++)
        gc_alloc_pair(h);

    gc_collect(h);

    gc_stats_t s = gc_get_stats(h);
    CHECK(s.live_object_count == 2,
          "expected 2 live objects in the cycle");

    gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

int main(void) {
    printf("=== Basic GC Tests ===\n");
    test_create_destroy();
    test_alloc_pair();
    test_alloc_vector();
    test_alloc_opaque();
    test_alloc_ephemeron();
    test_collect_all_garbage();
    test_collect_preserves_root();
    test_collect_traces_graph();
    test_collect_frees_memory();
    test_vector_references();
    test_multiple_roots();
    test_root_pop();
    test_stats_collection_count();
    test_cyclic_graph();

    printf("\nResults: %d passed, %d failed\n", tests_passed, tests_failed);
    if (tests_failed == 0) {
        printf("ALL TESTS PASSED\n");
        return 0;
    }
    return 1;
}
