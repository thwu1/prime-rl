#include "pool.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

static pool_header_t *alloc_list = NULL;
static int total_allocs = 0;
static int total_frees = 0;

void *pool_alloc(uint32_t pool_type, size_t size, uint32_t tag) {
    (void)pool_type;
    pool_header_t *hdr = (pool_header_t *)malloc(sizeof(pool_header_t) + size);
    if (!hdr) return NULL;

    hdr->tag = tag;
    hdr->size = (uint32_t)size;
    hdr->next = alloc_list;
    alloc_list = hdr;
    total_allocs++;

    void *data = (void *)(hdr + 1);
    memset(data, 0, size);
    return data;
}

void pool_free(void *ptr, uint32_t tag) {
    (void)tag;
    if (!ptr) return;
    pool_header_t *hdr = ((pool_header_t *)ptr) - 1;

    pool_header_t **pp = &alloc_list;
    while (*pp) {
        if (*pp == hdr) {
            *pp = hdr->next;
            break;
        }
        pp = &(*pp)->next;
    }
    total_frees++;
    free(hdr);
}

void pool_dump_stats(void) {
    fprintf(stderr, "[pool] allocs=%d frees=%d outstanding=%d\n",
            total_allocs, total_frees, total_allocs - total_frees);
}
