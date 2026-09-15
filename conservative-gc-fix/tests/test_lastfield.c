/*
 * test_lastfield.c - Verify the collector scans an object's entire
 * contents, including the very last pointer-sized word.
 *
 */
#include "gc.h"
#include <stdio.h>
#include <string.h>

typedef struct {
    long   padding[7];   /* 56 bytes of non-pointer data */
    void  *last;         /* pointer in the LAST word (offset 56) */
} test_obj_t;

static void *roots[16];

int main(void) {
    int i, ok = 1;
    test_obj_t *obj;
    char *target;

    gc_init(1024 * 1024);
    gc_add_root(roots, roots + 16);

    obj    = (test_obj_t *)gc_malloc(sizeof(test_obj_t));
    target = (char *)gc_malloc(32);
    if (!obj || !target) { printf("FAIL: alloc\n"); return 1; }

    memset(target, 0xCD, 32);
    memset(obj->padding, 0, sizeof(obj->padding));
    obj->last = target;

    roots[0] = obj;
    target = NULL;    /* drop direct reference to target */

    gc_collect();

    /* If the last word was scanned, target survived. */
    {
        char *check = (char *)obj->last;
        for (i = 0; i < 32; i++) {
            if ((unsigned char)check[i] != 0xCD) { ok = 0; break; }
        }
    }

    if (ok) printf("PASS\n");
    else    printf("FAIL: target collected — last field not scanned\n");

    gc_shutdown();
    return ok ? 0 : 1;
}
