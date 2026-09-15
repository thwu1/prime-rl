/*
 * test_ephemerons.c — Tests ephemeron semantics: fixpoint resolution,
 *                     chains, cycles, diamonds, and edge cases.
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
 * 1. Key alive  →  value kept alive
 * ================================================================ */
static void test_key_alive(void) {
    TEST("key alive -> value alive");
    gc_heap_t *h = gc_heap_create(0);

    gc_obj_t *kr = NULL, *er = NULL, *tmp = NULL;
    gc_root_push(h, &kr);
    gc_root_push(h, &er);
    gc_root_push(h, &tmp);

    gc_pair_t *key = gc_alloc_pair(h);
    kr = (gc_obj_t *)key;

    gc_pair_t *val = gc_alloc_pair(h);
    tmp = (gc_obj_t *)val;       /* temp-root so alloc_ephemeron is safe */

    gc_ephemeron_t *e = gc_alloc_ephemeron(h, kr, tmp);
    er = (gc_obj_t *)e;
    tmp = NULL;

    gc_collect(h);

    e = (gc_ephemeron_t *)er;
    CHECK(e->key   != NULL, "key should be alive");
    CHECK(e->value != NULL, "value should be alive (key is rooted)");

    gc_root_pop(h); gc_root_pop(h); gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ================================================================
 * 2. Key dead  →  ephemeron broken
 * ================================================================ */
static void test_key_dead(void) {
    TEST("key dead -> broken");
    gc_heap_t *h = gc_heap_create(0);

    gc_obj_t *er = NULL, *tmp = NULL;
    gc_root_push(h, &er);
    gc_root_push(h, &tmp);

    gc_pair_t *key = gc_alloc_pair(h);
    tmp = (gc_obj_t *)key;
    gc_pair_t *val = gc_alloc_pair(h);
    gc_obj_t *valp = (gc_obj_t *)val;
    /* val is unrooted but alive until next collect */

    gc_ephemeron_t *e = gc_alloc_ephemeron(h, tmp, valp);
    er = (gc_obj_t *)e;
    tmp = NULL;                  /* key loses its root */

    gc_collect(h);

    e = (gc_ephemeron_t *)er;
    CHECK(e->key   == NULL, "key should be NULL (broken)");
    CHECK(e->value == NULL, "value should be NULL (broken)");

    gc_root_pop(h); gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ================================================================
 * 3. Chain:  K1 (rooted)  →  E1(K1,V1)  →  E2(V1,V2)
 *    V1 is alive because K1 is alive (via E1).
 *    V2 is alive because V1 is alive (via E2).
 *    Removing root on K1 breaks the entire chain.
 * ================================================================ */
static void test_chain(void) {
    TEST("ephemeron chain");
    gc_heap_t *h = gc_heap_create(0);

    gc_obj_t *k1r = NULL, *e1r = NULL, *e2r = NULL, *tmp = NULL;
    gc_root_push(h, &k1r);
    gc_root_push(h, &e1r);
    gc_root_push(h, &e2r);
    gc_root_push(h, &tmp);

    gc_pair_t *k1 = gc_alloc_pair(h);
    k1r = (gc_obj_t *)k1;

    gc_pair_t *v1 = gc_alloc_pair(h);
    tmp = (gc_obj_t *)v1;

    gc_ephemeron_t *e1 = gc_alloc_ephemeron(h, k1r, tmp);
    e1r = (gc_obj_t *)e1;

    gc_pair_t *v2 = gc_alloc_pair(h);
    gc_obj_t *v2p = (gc_obj_t *)v2;

    gc_ephemeron_t *e2 = gc_alloc_ephemeron(h, tmp, v2p);
    e2r = (gc_obj_t *)e2;
    tmp = NULL;

    /* --- collect with K1 rooted --- */
    gc_collect(h);

    e1 = (gc_ephemeron_t *)e1r;
    e2 = (gc_ephemeron_t *)e2r;
    CHECK(e1->key   != NULL, "E1 key alive");
    CHECK(e1->value != NULL, "E1 value alive");
    CHECK(e2->key   != NULL, "E2 key alive (via E1 value)");
    CHECK(e2->value != NULL, "E2 value alive");

    /* --- remove K1 root --- */
    k1r = NULL;
    gc_collect(h);

    e1 = (gc_ephemeron_t *)e1r;
    e2 = (gc_ephemeron_t *)e2r;
    CHECK(e1->key   == NULL, "E1 should be broken");
    CHECK(e1->value == NULL, "E1 value should be NULL");
    CHECK(e2->key   == NULL, "E2 should be broken (V1 died)");
    CHECK(e2->value == NULL, "E2 value should be NULL");

    gc_root_pop(h); gc_root_pop(h); gc_root_pop(h); gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ================================================================
 * 4. Cycle through ephemerons (no external root for keys)
 *    E1(A, B)   E2(B, A)   — A alive iff B alive iff A alive.
 *    Both must break.
 * ================================================================ */
static void test_cycle(void) {
    TEST("ephemeron cycle (no external root)");
    gc_heap_t *h = gc_heap_create(0);

    gc_obj_t *e1r = NULL, *e2r = NULL, *t1 = NULL, *t2 = NULL;
    gc_root_push(h, &e1r);
    gc_root_push(h, &e2r);
    gc_root_push(h, &t1);
    gc_root_push(h, &t2);

    gc_pair_t *a = gc_alloc_pair(h);
    t1 = (gc_obj_t *)a;
    gc_pair_t *b = gc_alloc_pair(h);
    t2 = (gc_obj_t *)b;

    gc_ephemeron_t *e1 = gc_alloc_ephemeron(h, t1, t2);
    e1r = (gc_obj_t *)e1;
    gc_ephemeron_t *e2 = gc_alloc_ephemeron(h, t2, t1);
    e2r = (gc_obj_t *)e2;

    t1 = NULL;
    t2 = NULL;

    gc_collect(h);

    e1 = (gc_ephemeron_t *)e1r;
    e2 = (gc_ephemeron_t *)e2r;
    CHECK(e1->key == NULL, "E1 should be broken (cycle)");
    CHECK(e2->key == NULL, "E2 should be broken (cycle)");

    gc_root_pop(h); gc_root_pop(h); gc_root_pop(h); gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ================================================================
 * 5. Value alive through a separate root
 *    Ephemeron breaks, but value survives via direct root.
 * ================================================================ */
static void test_value_alive_other_root(void) {
    TEST("broken ephemeron, value alive via other root");
    gc_heap_t *h = gc_heap_create(0);

    gc_obj_t *vr = NULL, *er = NULL, *tmp = NULL;
    gc_root_push(h, &vr);
    gc_root_push(h, &er);
    gc_root_push(h, &tmp);

    gc_pair_t *key = gc_alloc_pair(h);
    tmp = (gc_obj_t *)key;
    gc_pair_t *val = gc_alloc_pair(h);
    vr = (gc_obj_t *)val;           /* value has its own root */

    gc_ephemeron_t *e = gc_alloc_ephemeron(h, tmp, vr);
    er = (gc_obj_t *)e;
    tmp = NULL;                       /* key dies */

    gc_collect(h);

    e = (gc_ephemeron_t *)er;
    CHECK(e->key   == NULL,          "broken");
    CHECK(e->value == NULL,          "value slot NULLed");
    CHECK(vr       != NULL,          "value alive via separate root");
    CHECK(vr->type == GC_TYPE_PAIR,  "value type ok");

    gc_root_pop(h); gc_root_pop(h); gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ================================================================
 * 6. Long chain (10 ephemerons)
 *    K0 (rooted) → E0(K0,V0) → E1(V0,V1) → … → E9(V8,V9)
 * ================================================================ */
static void test_long_chain(void) {
    TEST("long chain (10 ephemerons)");
    gc_heap_t *h = gc_heap_create(0);

    #define N 10
    gc_obj_t *roots[N + 2];
    for (int i = 0; i < N + 2; i++) {
        roots[i] = NULL;
        gc_root_push(h, &roots[i]);
    }
    /* roots[0]   = K0 (pair, rooted)
     * roots[1..N]= ephemerons E0..E9
     * roots[N+1] = temp scratch */

    gc_pair_t *k0 = gc_alloc_pair(h);
    roots[0] = (gc_obj_t *)k0;

    gc_obj_t *prev_val = roots[0];
    for (int i = 0; i < N; i++) {
        gc_pair_t *vi = gc_alloc_pair(h);
        roots[N + 1] = (gc_obj_t *)vi;            /* temp root */
        gc_ephemeron_t *ei = gc_alloc_ephemeron(h, prev_val, roots[N + 1]);
        roots[i + 1] = (gc_obj_t *)ei;
        prev_val = roots[N + 1];
        roots[N + 1] = NULL;
    }

    gc_collect(h);

    /* all should resolve */
    for (int i = 0; i < N; i++) {
        gc_ephemeron_t *ei = (gc_ephemeron_t *)roots[i + 1];
        if (ei->key == NULL || ei->value == NULL) {
            char buf[80];
            snprintf(buf, sizeof buf, "E%d should not be broken", i);
            FAIL(buf);
        }
    }

    /* kill K0 */
    roots[0] = NULL;
    gc_collect(h);

    for (int i = 0; i < N; i++) {
        gc_ephemeron_t *ei = (gc_ephemeron_t *)roots[i + 1];
        if (ei->key != NULL) {
            char buf[80];
            snprintf(buf, sizeof buf, "E%d should be broken after killing K0", i);
            FAIL(buf);
        }
    }

    for (int i = N + 1; i >= 0; i--) gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
    #undef N
}

/* ================================================================
 * 7. Diamond:  two ephemerons sharing the same key
 * ================================================================ */
static void test_diamond(void) {
    TEST("diamond (shared key)");
    gc_heap_t *h = gc_heap_create(0);

    gc_obj_t *kr = NULL, *e1r = NULL, *e2r = NULL, *tmp = NULL;
    gc_root_push(h, &kr);
    gc_root_push(h, &e1r);
    gc_root_push(h, &e2r);
    gc_root_push(h, &tmp);

    gc_pair_t *k = gc_alloc_pair(h);
    kr = (gc_obj_t *)k;

    gc_pair_t *v1 = gc_alloc_pair(h);
    tmp = (gc_obj_t *)v1;
    gc_ephemeron_t *e1 = gc_alloc_ephemeron(h, kr, tmp);
    e1r = (gc_obj_t *)e1;

    gc_pair_t *v2 = gc_alloc_pair(h);
    tmp = (gc_obj_t *)v2;
    gc_ephemeron_t *e2 = gc_alloc_ephemeron(h, kr, tmp);
    e2r = (gc_obj_t *)e2;
    tmp = NULL;

    gc_collect(h);
    e1 = (gc_ephemeron_t *)e1r;
    e2 = (gc_ephemeron_t *)e2r;
    CHECK(e1->key != NULL, "E1 alive");
    CHECK(e2->key != NULL, "E2 alive");

    kr = NULL;
    gc_collect(h);
    e1 = (gc_ephemeron_t *)e1r;
    e2 = (gc_ephemeron_t *)e2r;
    CHECK(e1->key == NULL, "E1 broken");
    CHECK(e2->key == NULL, "E2 broken");

    gc_root_pop(h); gc_root_pop(h); gc_root_pop(h); gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ================================================================
 * 8. Value traced transitively (value is a graph, not just a leaf)
 *    E(K, V1)  where  V1.car → V2 → V3
 * ================================================================ */
static void test_transitive_value(void) {
    TEST("value traced transitively");
    gc_heap_t *h = gc_heap_create(0);

    gc_obj_t *kr = NULL, *er = NULL, *tmp = NULL;
    gc_root_push(h, &kr);
    gc_root_push(h, &er);
    gc_root_push(h, &tmp);

    gc_pair_t *k = gc_alloc_pair(h);
    kr = (gc_obj_t *)k;

    /* build chain: v1->car = v2, v2->car = v3 */
    gc_pair_t *v3 = gc_alloc_pair(h);
    tmp = (gc_obj_t *)v3;

    gc_pair_t *v2 = gc_alloc_pair(h);
    v2->car = tmp;
    tmp = (gc_obj_t *)v2;

    gc_pair_t *v1 = gc_alloc_pair(h);
    v1->car = tmp;
    tmp = (gc_obj_t *)v1;

    gc_ephemeron_t *e = gc_alloc_ephemeron(h, kr, tmp);
    er = (gc_obj_t *)e;
    tmp = NULL;

    gc_collect(h);

    gc_stats_t s = gc_get_stats(h);
    /* key + v1 + v2 + v3 + ephemeron = 5 */
    CHECK(s.live_object_count == 5, "should have 5 live objects");

    gc_root_pop(h); gc_root_pop(h); gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ================================================================
 * 9. Key == value  (self-referencing ephemeron)
 * ================================================================ */
static void test_key_equals_value(void) {
    TEST("key == value");
    gc_heap_t *h = gc_heap_create(0);

    gc_obj_t *kr = NULL, *er = NULL;
    gc_root_push(h, &kr);
    gc_root_push(h, &er);

    gc_pair_t *k = gc_alloc_pair(h);
    kr = (gc_obj_t *)k;

    gc_ephemeron_t *e = gc_alloc_ephemeron(h, kr, kr);
    er = (gc_obj_t *)e;

    gc_collect(h);
    e = (gc_ephemeron_t *)er;
    CHECK(e->key   != NULL, "key alive");
    CHECK(e->value != NULL, "value alive");
    CHECK(e->key == e->value, "key and value should be same object");

    gc_root_pop(h); gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ================================================================
 * 10. Stats: broken/ephemeron counts
 * ================================================================ */
static void test_stats_ephemerons(void) {
    TEST("stats: ephemeron counts");
    gc_heap_t *h = gc_heap_create(0);

    gc_obj_t *kr = NULL, *e1r = NULL, *e2r = NULL, *tmp = NULL;
    gc_root_push(h, &kr);
    gc_root_push(h, &e1r);
    gc_root_push(h, &e2r);
    gc_root_push(h, &tmp);

    gc_pair_t *k_alive = gc_alloc_pair(h);
    kr = (gc_obj_t *)k_alive;

    /* E1: key alive */
    gc_pair_t *v1 = gc_alloc_pair(h);
    tmp = (gc_obj_t *)v1;
    gc_ephemeron_t *e1 = gc_alloc_ephemeron(h, kr, tmp);
    e1r = (gc_obj_t *)e1;

    /* E2: key dead */
    gc_pair_t *k_dead = gc_alloc_pair(h);
    tmp = (gc_obj_t *)k_dead;
    gc_pair_t *v2 = gc_alloc_pair(h);
    gc_ephemeron_t *e2 = gc_alloc_ephemeron(h, tmp, (gc_obj_t *)v2);
    e2r = (gc_obj_t *)e2;
    tmp = NULL;   /* k_dead loses root */

    gc_collect(h);

    gc_stats_t s = gc_get_stats(h);
    /* alive: k_alive, v1, E1 (not broken), E2 (broken) = 4 */
    CHECK(s.live_object_count       == 4, "4 live objects");
    CHECK(s.ephemeron_count         == 2, "2 ephemerons");
    CHECK(s.broken_ephemeron_count  == 1, "1 broken");

    gc_root_pop(h); gc_root_pop(h); gc_root_pop(h); gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ================================================================
 * 11. Ephemeron whose value is another ephemeron's key
 *     K1 (rooted), E1(K1, V1), E2(V1, V2)
 *     Both should resolve: V1 alive via E1, V2 alive via E2.
 * ================================================================ */
static void test_value_is_others_key(void) {
    TEST("value is another ephemeron's key");
    gc_heap_t *h = gc_heap_create(0);

    gc_obj_t *kr = NULL, *e1r = NULL, *e2r = NULL, *tmp = NULL;
    gc_root_push(h, &kr);
    gc_root_push(h, &e1r);
    gc_root_push(h, &e2r);
    gc_root_push(h, &tmp);

    gc_pair_t *k1 = gc_alloc_pair(h);
    kr = (gc_obj_t *)k1;

    gc_pair_t *v1 = gc_alloc_pair(h);
    tmp = (gc_obj_t *)v1;

    gc_ephemeron_t *e1 = gc_alloc_ephemeron(h, kr, tmp);
    e1r = (gc_obj_t *)e1;

    gc_pair_t *v2 = gc_alloc_pair(h);
    gc_obj_t *v2p = (gc_obj_t *)v2;

    gc_ephemeron_t *e2 = gc_alloc_ephemeron(h, tmp, v2p);
    e2r = (gc_obj_t *)e2;
    tmp = NULL;

    gc_collect(h);

    e1 = (gc_ephemeron_t *)e1r;
    e2 = (gc_ephemeron_t *)e2r;
    CHECK(e1->key   != NULL, "E1 not broken");
    CHECK(e1->value != NULL, "E1 value alive");
    CHECK(e2->key   != NULL, "E2 not broken (key=V1, alive via E1)");
    CHECK(e2->value != NULL, "E2 value alive");

    gc_root_pop(h); gc_root_pop(h); gc_root_pop(h); gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ================================================================
 * 12. Three-node cycle: E1(A,B), E2(B,C), E3(C,A) — all break
 * ================================================================ */
static void test_three_node_cycle(void) {
    TEST("three-node ephemeron cycle");
    gc_heap_t *h = gc_heap_create(0);

    gc_obj_t *e1r = NULL, *e2r = NULL, *e3r = NULL;
    gc_obj_t *t1 = NULL, *t2 = NULL, *t3 = NULL;
    gc_root_push(h, &e1r);
    gc_root_push(h, &e2r);
    gc_root_push(h, &e3r);
    gc_root_push(h, &t1);
    gc_root_push(h, &t2);
    gc_root_push(h, &t3);

    gc_pair_t *a = gc_alloc_pair(h); t1 = (gc_obj_t *)a;
    gc_pair_t *b = gc_alloc_pair(h); t2 = (gc_obj_t *)b;
    gc_pair_t *c = gc_alloc_pair(h); t3 = (gc_obj_t *)c;

    gc_ephemeron_t *e1 = gc_alloc_ephemeron(h, t1, t2);
    e1r = (gc_obj_t *)e1;
    gc_ephemeron_t *e2 = gc_alloc_ephemeron(h, t2, t3);
    e2r = (gc_obj_t *)e2;
    gc_ephemeron_t *e3 = gc_alloc_ephemeron(h, t3, t1);
    e3r = (gc_obj_t *)e3;

    t1 = NULL; t2 = NULL; t3 = NULL;

    gc_collect(h);

    CHECK(((gc_ephemeron_t *)e1r)->key == NULL, "E1 broken");
    CHECK(((gc_ephemeron_t *)e2r)->key == NULL, "E2 broken");
    CHECK(((gc_ephemeron_t *)e3r)->key == NULL, "E3 broken");

    for (int i = 0; i < 6; i++) gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ================================================================
 * 13. Partial cycle: one external root breaks the symmetry.
 *     E1(A,B), E2(B,A)  with A rooted  →  both resolve.
 * ================================================================ */
static void test_partial_cycle(void) {
    TEST("partial cycle (one external root)");
    gc_heap_t *h = gc_heap_create(0);

    gc_obj_t *ar = NULL, *e1r = NULL, *e2r = NULL, *tmp = NULL;
    gc_root_push(h, &ar);
    gc_root_push(h, &e1r);
    gc_root_push(h, &e2r);
    gc_root_push(h, &tmp);

    gc_pair_t *a = gc_alloc_pair(h); ar = (gc_obj_t *)a;
    gc_pair_t *b = gc_alloc_pair(h); tmp = (gc_obj_t *)b;

    gc_ephemeron_t *e1 = gc_alloc_ephemeron(h, ar, tmp);
    e1r = (gc_obj_t *)e1;
    gc_ephemeron_t *e2 = gc_alloc_ephemeron(h, tmp, ar);
    e2r = (gc_obj_t *)e2;
    tmp = NULL;

    gc_collect(h);

    gc_ephemeron_t *re1 = (gc_ephemeron_t *)e1r;
    gc_ephemeron_t *re2 = (gc_ephemeron_t *)e2r;
    /* A is rooted → E1 resolves (B alive) → E2 resolves (A already alive) */
    CHECK(re1->key != NULL, "E1 not broken");
    CHECK(re2->key != NULL, "E2 not broken");

    gc_root_pop(h); gc_root_pop(h); gc_root_pop(h); gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ================================================================
 * 14. Ephemeron value is itself an ephemeron
 * ================================================================ */
static void test_ephemeron_as_value(void) {
    TEST("ephemeron as value of another ephemeron");
    gc_heap_t *h = gc_heap_create(0);

    gc_obj_t *k1r = NULL, *k2r = NULL, *eor = NULL, *tmp = NULL;
    gc_root_push(h, &k1r);
    gc_root_push(h, &k2r);
    gc_root_push(h, &eor);
    gc_root_push(h, &tmp);

    gc_pair_t *k1 = gc_alloc_pair(h); k1r = (gc_obj_t *)k1;
    gc_pair_t *k2 = gc_alloc_pair(h); k2r = (gc_obj_t *)k2;
    gc_pair_t *v  = gc_alloc_pair(h); tmp = (gc_obj_t *)v;

    /* inner = E_inner(k2, v) */
    gc_ephemeron_t *inner = gc_alloc_ephemeron(h, k2r, tmp);
    tmp = (gc_obj_t *)inner;

    /* outer = E_outer(k1, inner) */
    gc_ephemeron_t *outer = gc_alloc_ephemeron(h, k1r, tmp);
    eor = (gc_obj_t *)outer;
    tmp = NULL;

    gc_collect(h);

    outer = (gc_ephemeron_t *)eor;
    CHECK(outer->key   != NULL, "outer not broken");
    CHECK(outer->value != NULL, "outer value alive");

    gc_ephemeron_t *inner_r = (gc_ephemeron_t *)outer->value;
    CHECK(inner_r->key   != NULL, "inner not broken");
    CHECK(inner_r->value != NULL, "inner value alive");

    gc_root_pop(h); gc_root_pop(h); gc_root_pop(h); gc_root_pop(h);
    gc_heap_destroy(h);
    PASS();
}

/* ---- main ---- */
int main(void) {
    printf("=== Ephemeron Tests ===\n");
    test_key_alive();
    test_key_dead();
    test_chain();
    test_cycle();
    test_value_alive_other_root();
    test_long_chain();
    test_diamond();
    test_transitive_value();
    test_key_equals_value();
    test_stats_ephemerons();
    test_value_is_others_key();
    test_three_node_cycle();
    test_partial_cycle();
    test_ephemeron_as_value();

    printf("\nResults: %d passed, %d failed\n", tests_passed, tests_failed);
    if (tests_failed == 0) {
        printf("ALL TESTS PASSED\n");
        return 0;
    }
    return 1;
}
