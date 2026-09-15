/*
 * test_dlink.c - Verify disappearing link semantics.
 *
 */
#include "gc.h"
#include <stdio.h>

static void *roots[16];

/* NOT a root — the GC must not scan this. */
static void *weak_ref;

int main(void) {
    gc_init(1024 * 1024);
    gc_add_root(roots, roots + 16);

    roots[0] = gc_malloc(64);
    if (!roots[0]) { printf("FAIL: alloc\n"); return 1; }

    weak_ref = roots[0];
    gc_register_disappearing_link(&weak_ref);

    /* Drop the strong reference; only the disappearing link remains. */
    roots[0] = NULL;
    gc_collect();

    if (weak_ref == NULL) {
        printf("PASS\n");
    } else {
        printf("FAIL: disappearing link was not nulled\n");
    }

    gc_shutdown();
    return (weak_ref == NULL) ? 0 : 1;
}
