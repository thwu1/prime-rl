
#include "hamt.h"
#include "murmur3.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ---- Hash and comparison functions ---- */

static uint32_t test_hash(const void *key, const size_t gen)
{
    return murmur3_32((uint8_t *)key, strlen((const char *)key), (uint32_t)gen);
}

static int test_cmp(const void *a, const void *b)
{
    size_t la = strlen((const char *)a);
    size_t lb = strlen((const char *)b);
    size_t n = la > lb ? la : lb;
    return strncmp((const char *)a, (const char *)b, n);
}

/* ---- Conflict resolution functions ---- */

static void *keep_left(const void *key, void *v1, void *v2)
{
    (void)key;
    (void)v2;
    return v1;
}

static void *keep_right(const void *key, void *v1, void *v2)
{
    (void)key;
    (void)v1;
    return v2;
}

/* ---- Test infrastructure ---- */

#define ASSERT(cond, msg)                                                      \
    do {                                                                       \
        if (!(cond)) {                                                         \
            printf("  FAIL [line %d]: %s\n", __LINE__, msg);                   \
            return 1;                                                          \
        }                                                                      \
    } while (0)

static struct hamt_config test_cfg;

static void init_config(void)
{
    test_cfg.ator = &hamt_allocator_default;
    test_cfg.key_cmp_fn = test_cmp;
    test_cfg.key_hash_fn = test_hash;
}

/* ---- Large-scale key storage ---- */

#define LARGE_N 2000
static char large_keys[LARGE_N][16];
static int large_vals[LARGE_N];

static void init_large_data(void)
{
    for (int i = 0; i < LARGE_N; i++) {
        snprintf(large_keys[i], 16, "key_%06d", i);
        large_vals[i] = i * 10;
    }
}

/* ========== UNION TESTS ========== */

static int test_union_empty_both(void)
{
    printf("  test_union_empty_both... ");
    struct hamt *t1 = hamt_create(&test_cfg);
    struct hamt *t2 = hamt_create(&test_cfg);

    const struct hamt *r = hamt_punion(t1, t2, keep_left);
    ASSERT(hamt_size(r) == 0, "union of two empties should be empty");

    hamt_delete(t1);
    hamt_delete(t2);
    printf("PASS\n");
    return 0;
}

static int test_union_one_empty(void)
{
    printf("  test_union_one_empty... ");
    struct hamt *t1 = hamt_create(&test_cfg);
    struct hamt *t2 = hamt_create(&test_cfg);
    static int v[] = {10, 20, 30};
    hamt_set(t1, "alpha", &v[0]);
    hamt_set(t1, "beta", &v[1]);
    hamt_set(t1, "gamma", &v[2]);

    const struct hamt *r1 = hamt_punion(t1, t2, keep_left);
    ASSERT(hamt_size(r1) == 3, "union(non-empty, empty) wrong size");
    ASSERT(hamt_get(r1, "alpha") == &v[0], "missing alpha");
    ASSERT(hamt_get(r1, "beta") == &v[1], "missing beta");
    ASSERT(hamt_get(r1, "gamma") == &v[2], "missing gamma");

    const struct hamt *r2 = hamt_punion(t2, t1, keep_left);
    ASSERT(hamt_size(r2) == 3, "union(empty, non-empty) wrong size");
    ASSERT(hamt_get(r2, "alpha") == &v[0], "missing alpha in r2");

    hamt_delete(t1);
    hamt_delete(t2);
    printf("PASS\n");
    return 0;
}

static int test_union_disjoint(void)
{
    printf("  test_union_disjoint... ");
    struct hamt *t1 = hamt_create(&test_cfg);
    struct hamt *t2 = hamt_create(&test_cfg);
    static int v1[] = {1, 2, 3, 4, 5};
    static int v2[] = {6, 7, 8, 9, 10};
    char *k1[] = {"alpha", "beta", "gamma", "delta", "epsilon"};
    char *k2[] = {"zeta", "eta", "theta", "iota", "kappa"};

    for (int i = 0; i < 5; i++) {
        hamt_set(t1, k1[i], &v1[i]);
        hamt_set(t2, k2[i], &v2[i]);
    }

    const struct hamt *r = hamt_punion(t1, t2, keep_left);
    ASSERT(hamt_size(r) == 10, "disjoint union should have 10 elements");
    for (int i = 0; i < 5; i++) {
        ASSERT(hamt_get(r, k1[i]) == &v1[i], "missing t1 key");
        ASSERT(hamt_get(r, k2[i]) == &v2[i], "missing t2 key");
    }

    hamt_delete(t1);
    hamt_delete(t2);
    printf("PASS\n");
    return 0;
}

static int test_union_overlap_keep_left(void)
{
    printf("  test_union_overlap_keep_left... ");
    struct hamt *t1 = hamt_create(&test_cfg);
    struct hamt *t2 = hamt_create(&test_cfg);
    static int v1[] = {10, 20, 30, 40, 50};
    static int v2[] = {300, 400, 500, 60, 70};
    char *k1[] = {"alpha", "beta", "gamma", "delta", "epsilon"};
    char *k2[] = {"gamma", "delta", "epsilon", "zeta", "eta"};

    for (int i = 0; i < 5; i++) {
        hamt_set(t1, k1[i], &v1[i]);
        hamt_set(t2, k2[i], &v2[i]);
    }

    const struct hamt *r = hamt_punion(t1, t2, keep_left);
    ASSERT(hamt_size(r) == 7, "partial overlap union size should be 7");

    /* t1-only keys */
    ASSERT(hamt_get(r, "alpha") == &v1[0], "alpha wrong");
    ASSERT(hamt_get(r, "beta") == &v1[1], "beta wrong");
    /* shared keys: keep_left should use t1 values */
    ASSERT(hamt_get(r, "gamma") == &v1[2], "gamma should be t1 value");
    ASSERT(hamt_get(r, "delta") == &v1[3], "delta should be t1 value");
    ASSERT(hamt_get(r, "epsilon") == &v1[4], "epsilon should be t1 value");
    /* t2-only keys */
    ASSERT(hamt_get(r, "zeta") == &v2[3], "zeta wrong");
    ASSERT(hamt_get(r, "eta") == &v2[4], "eta wrong");

    /* Verify inputs unchanged */
    ASSERT(hamt_size(t1) == 5, "t1 modified");
    ASSERT(hamt_size(t2) == 5, "t2 modified");

    hamt_delete(t1);
    hamt_delete(t2);
    printf("PASS\n");
    return 0;
}

static int test_union_overlap_keep_right(void)
{
    printf("  test_union_overlap_keep_right... ");
    struct hamt *t1 = hamt_create(&test_cfg);
    struct hamt *t2 = hamt_create(&test_cfg);
    static int v1[] = {10, 20, 30};
    static int v2[] = {100, 200, 300};
    char *shared[] = {"aaa", "bbb", "ccc"};

    for (int i = 0; i < 3; i++) {
        hamt_set(t1, shared[i], &v1[i]);
        hamt_set(t2, shared[i], &v2[i]);
    }

    const struct hamt *r = hamt_punion(t1, t2, keep_right);
    ASSERT(hamt_size(r) == 3, "full overlap union size should be 3");
    /* keep_right should use t2 values */
    ASSERT(hamt_get(r, "aaa") == &v2[0], "aaa should be t2 value");
    ASSERT(hamt_get(r, "bbb") == &v2[1], "bbb should be t2 value");
    ASSERT(hamt_get(r, "ccc") == &v2[2], "ccc should be t2 value");

    hamt_delete(t1);
    hamt_delete(t2);
    printf("PASS\n");
    return 0;
}

/* ========== INTERSECTION TESTS ========== */

static int test_intersection_empty(void)
{
    printf("  test_intersection_empty... ");
    struct hamt *t1 = hamt_create(&test_cfg);
    struct hamt *t2 = hamt_create(&test_cfg);
    static int v[] = {1, 2, 3};
    hamt_set(t1, "x", &v[0]);
    hamt_set(t1, "y", &v[1]);
    hamt_set(t1, "z", &v[2]);

    const struct hamt *r = hamt_pintersection(t1, t2, keep_left);
    ASSERT(hamt_size(r) == 0, "intersection with empty should be empty");

    const struct hamt *r2 = hamt_pintersection(t2, t1, keep_left);
    ASSERT(hamt_size(r2) == 0, "intersection of empty with non-empty should be empty");

    hamt_delete(t1);
    hamt_delete(t2);
    printf("PASS\n");
    return 0;
}

static int test_intersection_disjoint(void)
{
    printf("  test_intersection_disjoint... ");
    struct hamt *t1 = hamt_create(&test_cfg);
    struct hamt *t2 = hamt_create(&test_cfg);
    static int v1[] = {1, 2, 3};
    static int v2[] = {4, 5, 6};

    hamt_set(t1, "alpha", &v1[0]);
    hamt_set(t1, "beta", &v1[1]);
    hamt_set(t1, "gamma", &v1[2]);
    hamt_set(t2, "delta", &v2[0]);
    hamt_set(t2, "epsilon", &v2[1]);
    hamt_set(t2, "zeta", &v2[2]);

    const struct hamt *r = hamt_pintersection(t1, t2, keep_left);
    ASSERT(hamt_size(r) == 0, "intersection of disjoint should be empty");

    hamt_delete(t1);
    hamt_delete(t2);
    printf("PASS\n");
    return 0;
}

static int test_intersection_overlap(void)
{
    printf("  test_intersection_overlap... ");
    struct hamt *t1 = hamt_create(&test_cfg);
    struct hamt *t2 = hamt_create(&test_cfg);
    static int v1[] = {10, 20, 30, 40, 50};
    static int v2[] = {300, 400, 500, 60, 70};
    char *k1[] = {"alpha", "beta", "gamma", "delta", "epsilon"};
    char *k2[] = {"gamma", "delta", "epsilon", "zeta", "eta"};

    for (int i = 0; i < 5; i++) {
        hamt_set(t1, k1[i], &v1[i]);
        hamt_set(t2, k2[i], &v2[i]);
    }

    const struct hamt *r = hamt_pintersection(t1, t2, keep_left);
    ASSERT(hamt_size(r) == 3, "intersection size should be 3");
    /* Only shared keys present */
    ASSERT(hamt_get(r, "gamma") == &v1[2], "gamma should be t1 value (keep_left)");
    ASSERT(hamt_get(r, "delta") == &v1[3], "delta should be t1 value");
    ASSERT(hamt_get(r, "epsilon") == &v1[4], "epsilon should be t1 value");
    /* Non-shared keys absent */
    ASSERT(hamt_get(r, "alpha") == NULL, "alpha should not be in intersection");
    ASSERT(hamt_get(r, "beta") == NULL, "beta should not be in intersection");
    ASSERT(hamt_get(r, "zeta") == NULL, "zeta should not be in intersection");
    ASSERT(hamt_get(r, "eta") == NULL, "eta should not be in intersection");

    /* Verify inputs unchanged */
    ASSERT(hamt_size(t1) == 5, "t1 modified");
    ASSERT(hamt_size(t2) == 5, "t2 modified");

    hamt_delete(t1);
    hamt_delete(t2);
    printf("PASS\n");
    return 0;
}

static int test_intersection_full(void)
{
    printf("  test_intersection_full... ");
    struct hamt *t1 = hamt_create(&test_cfg);
    struct hamt *t2 = hamt_create(&test_cfg);
    static int v1[] = {10, 20, 30};
    static int v2[] = {100, 200, 300};
    char *keys[] = {"aaa", "bbb", "ccc"};

    for (int i = 0; i < 3; i++) {
        hamt_set(t1, keys[i], &v1[i]);
        hamt_set(t2, keys[i], &v2[i]);
    }

    const struct hamt *r = hamt_pintersection(t1, t2, keep_right);
    ASSERT(hamt_size(r) == 3, "full intersection size should be 3");
    ASSERT(hamt_get(r, "aaa") == &v2[0], "aaa should be t2 value (keep_right)");
    ASSERT(hamt_get(r, "bbb") == &v2[1], "bbb should be t2 value");
    ASSERT(hamt_get(r, "ccc") == &v2[2], "ccc should be t2 value");

    hamt_delete(t1);
    hamt_delete(t2);
    printf("PASS\n");
    return 0;
}

/* ========== DIFFERENCE TESTS ========== */

static int test_difference_with_empty(void)
{
    printf("  test_difference_with_empty... ");
    struct hamt *t1 = hamt_create(&test_cfg);
    struct hamt *t2 = hamt_create(&test_cfg);
    static int v[] = {1, 2, 3};
    hamt_set(t1, "x", &v[0]);
    hamt_set(t1, "y", &v[1]);
    hamt_set(t1, "z", &v[2]);

    const struct hamt *r = hamt_pdifference(t1, t2);
    ASSERT(hamt_size(r) == 3, "diff(t, empty) should equal t");
    ASSERT(hamt_get(r, "x") == &v[0], "missing x");
    ASSERT(hamt_get(r, "y") == &v[1], "missing y");
    ASSERT(hamt_get(r, "z") == &v[2], "missing z");

    const struct hamt *r2 = hamt_pdifference(t2, t1);
    ASSERT(hamt_size(r2) == 0, "diff(empty, t) should be empty");

    hamt_delete(t1);
    hamt_delete(t2);
    printf("PASS\n");
    return 0;
}

static int test_difference_same_keys(void)
{
    printf("  test_difference_same_keys... ");
    struct hamt *t1 = hamt_create(&test_cfg);
    struct hamt *t2 = hamt_create(&test_cfg);
    static int v1[] = {10, 20, 30};
    static int v2[] = {100, 200, 300};
    char *keys[] = {"aaa", "bbb", "ccc"};

    for (int i = 0; i < 3; i++) {
        hamt_set(t1, keys[i], &v1[i]);
        hamt_set(t2, keys[i], &v2[i]);
    }

    const struct hamt *r = hamt_pdifference(t1, t2);
    ASSERT(hamt_size(r) == 0, "diff with same keys should be empty");

    hamt_delete(t1);
    hamt_delete(t2);
    printf("PASS\n");
    return 0;
}

static int test_difference_disjoint(void)
{
    printf("  test_difference_disjoint... ");
    struct hamt *t1 = hamt_create(&test_cfg);
    struct hamt *t2 = hamt_create(&test_cfg);
    static int v1[] = {1, 2, 3};
    static int v2[] = {4, 5, 6};

    hamt_set(t1, "alpha", &v1[0]);
    hamt_set(t1, "beta", &v1[1]);
    hamt_set(t1, "gamma", &v1[2]);
    hamt_set(t2, "delta", &v2[0]);
    hamt_set(t2, "epsilon", &v2[1]);
    hamt_set(t2, "zeta", &v2[2]);

    const struct hamt *r = hamt_pdifference(t1, t2);
    ASSERT(hamt_size(r) == 3, "diff of disjoint should keep all of t1");
    ASSERT(hamt_get(r, "alpha") == &v1[0], "missing alpha");
    ASSERT(hamt_get(r, "beta") == &v1[1], "missing beta");
    ASSERT(hamt_get(r, "gamma") == &v1[2], "missing gamma");

    hamt_delete(t1);
    hamt_delete(t2);
    printf("PASS\n");
    return 0;
}

static int test_difference_partial(void)
{
    printf("  test_difference_partial... ");
    struct hamt *t1 = hamt_create(&test_cfg);
    struct hamt *t2 = hamt_create(&test_cfg);
    static int v1[] = {10, 20, 30, 40, 50};
    static int v2[] = {300, 400, 500, 60, 70};
    char *k1[] = {"alpha", "beta", "gamma", "delta", "epsilon"};
    char *k2[] = {"gamma", "delta", "epsilon", "zeta", "eta"};

    for (int i = 0; i < 5; i++) {
        hamt_set(t1, k1[i], &v1[i]);
        hamt_set(t2, k2[i], &v2[i]);
    }

    const struct hamt *r = hamt_pdifference(t1, t2);
    ASSERT(hamt_size(r) == 2, "partial diff size should be 2");
    ASSERT(hamt_get(r, "alpha") == &v1[0], "alpha missing");
    ASSERT(hamt_get(r, "beta") == &v1[1], "beta missing");
    ASSERT(hamt_get(r, "gamma") == NULL, "gamma should be removed");
    ASSERT(hamt_get(r, "delta") == NULL, "delta should be removed");
    ASSERT(hamt_get(r, "epsilon") == NULL, "epsilon should be removed");

    /* Verify inputs unchanged */
    ASSERT(hamt_size(t1) == 5, "t1 modified");
    ASSERT(hamt_size(t2) == 5, "t2 modified");

    hamt_delete(t1);
    hamt_delete(t2);
    printf("PASS\n");
    return 0;
}

/* ========== LARGE-SCALE TESTS ========== */

static int test_large_union(void)
{
    printf("  test_large_union (1000+1000, 500 overlap)... ");
    struct hamt *t1 = hamt_create(&test_cfg);
    struct hamt *t2 = hamt_create(&test_cfg);

    /* t1: keys 0..999, t2: keys 500..1499, overlap: 500..999 */
    for (int i = 0; i < 1000; i++)
        hamt_set(t1, large_keys[i], &large_vals[i]);
    for (int i = 500; i < 1500; i++)
        hamt_set(t2, large_keys[i], &large_vals[i]);

    ASSERT(hamt_size(t1) == 1000, "t1 size wrong");
    ASSERT(hamt_size(t2) == 1000, "t2 size wrong");

    const struct hamt *r = hamt_punion(t1, t2, keep_left);
    ASSERT(hamt_size(r) == 1500, "large union size should be 1500");

    /* Verify all keys present */
    for (int i = 0; i < 1500; i++) {
        const void *v = hamt_get(r, large_keys[i]);
        ASSERT(v != NULL, "missing key in large union");
        /* For overlapping keys (500-999), keep_left should give t1 values */
        if (i < 1000) {
            ASSERT(v == &large_vals[i], "wrong value for t1 key in union");
        }
    }

    /* Verify inputs unchanged */
    ASSERT(hamt_size(t1) == 1000, "t1 modified after large union");
    ASSERT(hamt_size(t2) == 1000, "t2 modified after large union");

    hamt_delete(t1);
    hamt_delete(t2);
    printf("PASS\n");
    return 0;
}

static int test_large_intersection(void)
{
    printf("  test_large_intersection (1000+1000, 500 overlap)... ");
    struct hamt *t1 = hamt_create(&test_cfg);
    struct hamt *t2 = hamt_create(&test_cfg);

    for (int i = 0; i < 1000; i++)
        hamt_set(t1, large_keys[i], &large_vals[i]);
    for (int i = 500; i < 1500; i++)
        hamt_set(t2, large_keys[i], &large_vals[i]);

    const struct hamt *r = hamt_pintersection(t1, t2, keep_left);
    ASSERT(hamt_size(r) == 500, "large intersection size should be 500");

    /* Only keys 500-999 should be present */
    for (int i = 0; i < 500; i++) {
        ASSERT(hamt_get(r, large_keys[i]) == NULL,
               "t1-only key should not be in intersection");
    }
    for (int i = 500; i < 1000; i++) {
        const void *v = hamt_get(r, large_keys[i]);
        ASSERT(v != NULL, "shared key missing from intersection");
        ASSERT(v == &large_vals[i], "wrong value in intersection (keep_left)");
    }
    for (int i = 1000; i < 1500; i++) {
        ASSERT(hamt_get(r, large_keys[i]) == NULL,
               "t2-only key should not be in intersection");
    }

    hamt_delete(t1);
    hamt_delete(t2);
    printf("PASS\n");
    return 0;
}

static int test_large_difference(void)
{
    printf("  test_large_difference (1000+1000, 500 overlap)... ");
    struct hamt *t1 = hamt_create(&test_cfg);
    struct hamt *t2 = hamt_create(&test_cfg);

    for (int i = 0; i < 1000; i++)
        hamt_set(t1, large_keys[i], &large_vals[i]);
    for (int i = 500; i < 1500; i++)
        hamt_set(t2, large_keys[i], &large_vals[i]);

    const struct hamt *r = hamt_pdifference(t1, t2);
    ASSERT(hamt_size(r) == 500, "large difference size should be 500");

    /* Only keys 0-499 should be present */
    for (int i = 0; i < 500; i++) {
        const void *v = hamt_get(r, large_keys[i]);
        ASSERT(v != NULL, "t1-only key missing from difference");
        ASSERT(v == &large_vals[i], "wrong value in difference");
    }
    for (int i = 500; i < 1000; i++) {
        ASSERT(hamt_get(r, large_keys[i]) == NULL,
               "shared key should not be in difference");
    }

    hamt_delete(t1);
    hamt_delete(t2);
    printf("PASS\n");
    return 0;
}

/* ========== PERSISTENCE TEST ========== */

static int test_persistence(void)
{
    printf("  test_persistence... ");
    struct hamt *t1 = hamt_create(&test_cfg);
    struct hamt *t2 = hamt_create(&test_cfg);
    static int v1[] = {10, 20, 30};
    static int v2[] = {100, 200, 300};

    hamt_set(t1, "aaa", &v1[0]);
    hamt_set(t1, "bbb", &v1[1]);
    hamt_set(t1, "ccc", &v1[2]);
    hamt_set(t2, "bbb", &v2[0]);
    hamt_set(t2, "ccc", &v2[1]);
    hamt_set(t2, "ddd", &v2[2]);

    /* After all set operations, originals must be unchanged */
    const struct hamt *u = hamt_punion(t1, t2, keep_left);
    const struct hamt *n = hamt_pintersection(t1, t2, keep_left);
    const struct hamt *d = hamt_pdifference(t1, t2);
    (void)u;
    (void)n;
    (void)d;

    /* Verify t1 */
    ASSERT(hamt_size(t1) == 3, "t1 size changed");
    ASSERT(hamt_get(t1, "aaa") == &v1[0], "t1 aaa changed");
    ASSERT(hamt_get(t1, "bbb") == &v1[1], "t1 bbb changed");
    ASSERT(hamt_get(t1, "ccc") == &v1[2], "t1 ccc changed");
    ASSERT(hamt_get(t1, "ddd") == NULL, "t1 gained ddd");

    /* Verify t2 */
    ASSERT(hamt_size(t2) == 3, "t2 size changed");
    ASSERT(hamt_get(t2, "bbb") == &v2[0], "t2 bbb changed");
    ASSERT(hamt_get(t2, "ccc") == &v2[1], "t2 ccc changed");
    ASSERT(hamt_get(t2, "ddd") == &v2[2], "t2 ddd changed");
    ASSERT(hamt_get(t2, "aaa") == NULL, "t2 gained aaa");

    hamt_delete(t1);
    hamt_delete(t2);
    printf("PASS\n");
    return 0;
}

/* ========== SINGLE ELEMENT EDGE CASE ========== */

static int test_single_element(void)
{
    printf("  test_single_element... ");
    struct hamt *t1 = hamt_create(&test_cfg);
    struct hamt *t2 = hamt_create(&test_cfg);
    static int v1 = 42;
    static int v2 = 99;

    hamt_set(t1, "only", &v1);
    hamt_set(t2, "only", &v2);

    /* Union of single-element tries with same key */
    const struct hamt *u = hamt_punion(t1, t2, keep_left);
    ASSERT(hamt_size(u) == 1, "single union size");
    ASSERT(hamt_get(u, "only") == &v1, "single union value");

    /* Intersection */
    const struct hamt *n = hamt_pintersection(t1, t2, keep_right);
    ASSERT(hamt_size(n) == 1, "single intersect size");
    ASSERT(hamt_get(n, "only") == &v2, "single intersect value");

    /* Difference */
    const struct hamt *d = hamt_pdifference(t1, t2);
    ASSERT(hamt_size(d) == 0, "single diff same key should be empty");

    hamt_delete(t1);
    hamt_delete(t2);
    printf("PASS\n");
    return 0;
}

/* ========== MAIN ========== */

int main(void)
{
    init_config();
    init_large_data();

    printf("=== HAMT Set Operations Tests ===\n");
    int failures = 0;

    /* Union tests */
    printf("Union:\n");
    failures += test_union_empty_both();
    failures += test_union_one_empty();
    failures += test_union_disjoint();
    failures += test_union_overlap_keep_left();
    failures += test_union_overlap_keep_right();

    /* Intersection tests */
    printf("Intersection:\n");
    failures += test_intersection_empty();
    failures += test_intersection_disjoint();
    failures += test_intersection_overlap();
    failures += test_intersection_full();

    /* Difference tests */
    printf("Difference:\n");
    failures += test_difference_with_empty();
    failures += test_difference_same_keys();
    failures += test_difference_disjoint();
    failures += test_difference_partial();

    /* Large-scale tests */
    printf("Large-scale:\n");
    failures += test_large_union();
    failures += test_large_intersection();
    failures += test_large_difference();

    /* Edge cases */
    printf("Edge cases:\n");
    failures += test_persistence();
    failures += test_single_element();

    printf("\n");
    if (failures == 0) {
        printf("ALL TESTS PASSED\n");
    } else {
        printf("%d TEST(S) FAILED\n", failures);
    }
    return failures != 0 ? 1 : 0;
}
