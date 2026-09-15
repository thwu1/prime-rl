#ifndef WALLOC_NATIVE_H
#define WALLOC_NATIVE_H

#include <stddef.h>

struct walloc_stats {
    size_t total_allocated_bytes;
    size_t total_freed_bytes;
    size_t current_live_bytes;
    size_t peak_live_bytes;
    size_t num_pages;
    double fragmentation_ratio;
};

void  walloc_init(void);
void  walloc_destroy(void);
void *walloc_malloc(size_t size);
void  walloc_free(void *ptr);
void *walloc_realloc(void *ptr, size_t size);
void *walloc_calloc(size_t nmemb, size_t size);
void  walloc_get_stats(struct walloc_stats *stats);

#endif /* WALLOC_NATIVE_H */
