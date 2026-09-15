/*
 * test_basic.c - Verify basic allocation and collection.
 *
 */
#include "gc.h"
#include <stdio.h>
#include <string.h>

static void *roots[16];

int main(void) {
    int i, ok = 1;
    unsigned char *p0, *p1;
    size_t free_before, free_after;
    void *temp;

    gc_init(1024 * 1024);
    gc_add_root(roots, roots + 16);

    roots[0] = gc_malloc(64);
    roots[1] = gc_malloc(128);
    temp = gc_malloc(256);          /* not rooted */

    if (!roots[0] || !roots[1] || !temp) {
        printf("FAIL: allocation returned NULL\n");
        return 1;
    }

    memset(roots[0], 0xAA, 64);
    memset(roots[1], 0xBB, 128);
    memset(temp, 0xCC, 256);

    free_before = gc_free_bytes();
    temp = NULL;                    /* drop unrooted reference */
    gc_collect();
    free_after = gc_free_bytes();

    p0 = (unsigned char *)roots[0];
    p1 = (unsigned char *)roots[1];

    for (i = 0; i < 64; i++)
        if (p0[i] != 0xAA) { ok = 0; break; }
    for (i = 0; i < 128; i++)
        if (p1[i] != 0xBB) { ok = 0; break; }

    if (free_after <= free_before) ok = 0;

    if (ok) printf("PASS\n");
    else    printf("FAIL: rooted object corrupted or garbage not collected\n");

    gc_shutdown();
    return ok ? 0 : 1;
}
