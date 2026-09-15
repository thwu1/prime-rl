/*
 * Memory pool allocator — implement the API declared in allocator.h.
 */

#include "allocator.h"
#include <stdint.h>
#include <string.h>

/* ── Implement all functions below ──────────────────────────────── */

mem_pool_t *pool_create(void *region, size_t region_size)
{
    (void)region;
    (void)region_size;
    return NULL;
}

void pool_destroy(mem_pool_t *pool)
{
    (void)pool;
}

void *pool_malloc(mem_pool_t *pool, size_t size)
{
    (void)pool;
    (void)size;
    return NULL;
}

void pool_free(mem_pool_t *pool, void *ptr)
{
    (void)pool;
    (void)ptr;
}

void *pool_calloc(mem_pool_t *pool, size_t count, size_t size)
{
    (void)pool;
    (void)count;
    (void)size;
    return NULL;
}

void *pool_realloc(mem_pool_t *pool, void *ptr, size_t new_size)
{
    (void)pool;
    (void)ptr;
    (void)new_size;
    return NULL;
}

void *pool_aligned_malloc(mem_pool_t *pool, size_t alignment, size_t size)
{
    (void)pool;
    (void)alignment;
    (void)size;
    return NULL;
}

void pool_aligned_free(mem_pool_t *pool, void *ptr)
{
    (void)pool;
    (void)ptr;
}

int pool_get_stats(mem_pool_t *pool, pool_stats_t *stats)
{
    (void)pool;
    (void)stats;
    return -1;
}

int pool_set_lock(mem_pool_t *pool,
                  void (*lock_fn)(void *ctx),
                  void (*unlock_fn)(void *ctx),
                  void *ctx)
{
    (void)pool;
    (void)lock_fn;
    (void)unlock_fn;
    (void)ctx;
    return -1;
}
