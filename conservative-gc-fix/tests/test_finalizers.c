/*
 * test_finalizers.c - Three sub-tests for finalization behaviour:
 *   1. Finalizer data validity  (sees live data, not zeroed memory)
 *   2. Topological ordering     (A→B→C ⇒ finalize A, B, C in that order)
 *   3. Cycle detection          (A↔B cycle ⇒ neither finalized; C finalized)
 *
 */
#include "gc.h"
#include <stdio.h>
#include <string.h>

static void *roots[32];

/* ---- Sub-test 1: data validity ---- */
static int data_test_ok = 0;

static void data_fin(void *obj, void *cd) {
    unsigned char *p = (unsigned char *)obj;
    int i, good = 1;
    (void)cd;
    for (i = 0; i < 32; i++)
        if (p[i] != 0xEE) { good = 0; break; }
    data_test_ok = good;
}

static int test_finalizer_data(void) {
    data_test_ok = 0;
    roots[0] = gc_malloc(32);
    if (!roots[0]) { printf("FAIL: finalizer_data alloc\n"); return 0; }
    memset(roots[0], 0xEE, 32);
    gc_register_finalizer(roots[0], data_fin, NULL);
    roots[0] = NULL;
    gc_collect();
    if (data_test_ok) { printf("PASS: finalizer_data\n"); return 1; }
    printf("FAIL: finalizer_data — finalizer did not see valid data\n");
    return 0;
}

/* ---- Sub-test 2: topological ordering ---- */
static int order_idx = 0;
static void *ordered[3];

static void order_fin(void *obj, void *cd) {
    (void)cd;
    if (order_idx < 3) ordered[order_idx++] = obj;
}

typedef struct chain_node { struct chain_node *next; } chain_node_t;

static int test_finalizer_order(void) {
    void *a, *b, *c;
    chain_node_t *A, *B, *C;
    int i;

    order_idx = 0;
    memset(ordered, 0, sizeof(ordered));

    roots[0] = gc_malloc(sizeof(chain_node_t));
    roots[1] = gc_malloc(sizeof(chain_node_t));
    roots[2] = gc_malloc(sizeof(chain_node_t));
    A = (chain_node_t *)roots[0];
    B = (chain_node_t *)roots[1];
    C = (chain_node_t *)roots[2];
    if (!A || !B || !C) { printf("FAIL: finalizer_order alloc\n"); return 0; }

    A->next = B;
    B->next = C;
    C->next = NULL;
    a = A; b = B; c = C;

    gc_register_finalizer(A, order_fin, NULL);
    gc_register_finalizer(B, order_fin, NULL);
    gc_register_finalizer(C, order_fin, NULL);

    roots[0] = roots[1] = roots[2] = NULL;
    gc_collect();

    if (order_idx == 3 && ordered[0] == a &&
        ordered[1] == b && ordered[2] == c) {
        printf("PASS: finalizer_order\n");
        return 1;
    }
    printf("FAIL: finalizer_order — expected [A,B,C], got %d entries:", order_idx);
    for (i = 0; i < order_idx; i++) {
        const char *n = "?";
        if (ordered[i] == a) n = "A";
        else if (ordered[i] == b) n = "B";
        else if (ordered[i] == c) n = "C";
        printf(" %s", n);
    }
    printf("\n");
    return 0;
}

/* ---- Sub-test 3: cycle detection ---- */
static int cyc_a = 0, cyc_b = 0, cyc_c = 0;

static void cyc_fin_a(void *obj, void *d) { (void)obj; (void)d; cyc_a = 1; }
static void cyc_fin_b(void *obj, void *d) { (void)obj; (void)d; cyc_b = 1; }
static void cyc_fin_c(void *obj, void *d) { (void)obj; (void)d; cyc_c = 1; }

typedef struct cnode { struct cnode *other; } cnode_t;

static int test_finalizer_cycle(void) {
    cnode_t *A, *B, *C;
    int pass = 1;

    cyc_a = cyc_b = cyc_c = 0;

    roots[0] = gc_malloc(sizeof(cnode_t));
    roots[1] = gc_malloc(sizeof(cnode_t));
    roots[2] = gc_malloc(sizeof(cnode_t));
    A = (cnode_t *)roots[0];
    B = (cnode_t *)roots[1];
    C = (cnode_t *)roots[2];
    if (!A || !B || !C) { printf("FAIL: finalizer_cycle alloc\n"); return 0; }

    A->other = B;
    B->other = A;   /* cycle */
    C->other = NULL; /* no cycle */

    gc_register_finalizer(A, cyc_fin_a, NULL);
    gc_register_finalizer(B, cyc_fin_b, NULL);
    gc_register_finalizer(C, cyc_fin_c, NULL);

    roots[0] = roots[1] = roots[2] = NULL;
    gc_collect();

    if (cyc_a || cyc_b) {
        printf("FAIL: finalizer_cycle — cyclic objects finalized (A=%d B=%d)\n",
               cyc_a, cyc_b);
        pass = 0;
    }
    if (!cyc_c) {
        printf("FAIL: finalizer_cycle — non-cyclic C was not finalized\n");
        pass = 0;
    }
    if (pass) printf("PASS: finalizer_cycle\n");
    return pass;
}

/* ---- main ---- */
int main(void) {
    int passed = 0;

    gc_init(2 * 1024 * 1024);
    gc_add_root(roots, roots + 32);
    passed += test_finalizer_data();

    gc_shutdown();
    gc_init(2 * 1024 * 1024);
    gc_add_root(roots, roots + 32);
    passed += test_finalizer_order();

    gc_shutdown();
    gc_init(2 * 1024 * 1024);
    gc_add_root(roots, roots + 32);
    passed += test_finalizer_cycle();

    gc_shutdown();
    printf("finalizers: %d/3 passed\n", passed);
    return (passed == 3) ? 0 : 1;
}
