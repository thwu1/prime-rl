/*
 *
 * Minimal smoke test for the hash-map implementation.
 * Build:  make
 * Run:    ./hashmap_test
 */
#include <stdio.h>
#include <string.h>
#include <assert.h>
#include "hashmap.h"

static int count_cb(const void *k, size_t kl, const void *v, size_t vl,
                    void *ud) {
    (void)k; (void)kl; (void)v; (void)vl;
    (*(int *)ud)++;
    return 0;
}

int main(void) {
    hashmap_t *m = hm_create(16);
    assert(m);

    /* insert + lookup */
    assert(hm_insert(m, "hello", 5, "world", 5) == 0);
    const void *val;
    size_t vlen;
    assert(hm_lookup(m, "hello", 5, &val, &vlen) == 0);
    assert(vlen == 5 && memcmp(val, "world", 5) == 0);

    /* update */
    assert(hm_insert(m, "hello", 5, "earth", 5) == 0);
    assert(hm_lookup(m, "hello", 5, &val, &vlen) == 0);
    assert(vlen == 5 && memcmp(val, "earth", 5) == 0);

    /* delete */
    assert(hm_delete(m, "hello", 5) == 0);
    assert(hm_lookup(m, "hello", 5, &val, &vlen) == -1);

    /* bulk insert */
    char buf[32];
    for (int i = 0; i < 200; i++) {
        int n = snprintf(buf, sizeof buf, "key-%d", i);
        assert(hm_insert(m, buf, n, buf, n) == 0);
    }

    /* stats */
    hm_stats_t st;
    hm_stats(m, &st);
    assert(st.size == 200);
    printf("size=%zu cap=%zu max_disp=%zu avg_disp=%.2f mem=%zu resizing=%zu\n",
           st.size, st.capacity, st.max_displacement,
           st.avg_displacement, st.memory_bytes, st.resize_remaining);

    /* iterate */
    int cnt = 0;
    size_t visited = hm_iterate(m, count_cb, &cnt);
    assert(visited == 200 && cnt == 200);

    hm_destroy(m);
    printf("All basic checks passed.\n");
    return 0;
}
