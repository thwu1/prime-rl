/*
 * test_interior.c - Verify interior-pointer scanning.
 *
 * A root holds a pointer into the MIDDLE of a heap object.
 * The collector must recognise interior pointers and keep the
 * containing object alive.
 *
 */
#include "gc.h"
#include <stdio.h>
#include <string.h>

static void *roots[16];

int main(void) {
    int i, ok = 1;
    char *obj;
    char *recovered;

    gc_init(1024 * 1024);
    gc_add_root(roots, roots + 16);

    obj = (char *)gc_malloc(128);
    if (!obj) { printf("FAIL: alloc\n"); return 1; }
    memset(obj, 0xAB, 128);

    /* Store ONLY an interior pointer (offset 40) in the root set. */
    roots[0] = obj + 40;
    obj = NULL;  /* drop exact-start reference */

    gc_collect();

    recovered = (char *)roots[0] - 40;
    for (i = 0; i < 128; i++) {
        if ((unsigned char)recovered[i] != 0xAB) { ok = 0; break; }
    }

    if (ok) printf("PASS\n");
    else    printf("FAIL: object collected despite interior pointer in root\n");

    gc_shutdown();
    return ok ? 0 : 1;
}
