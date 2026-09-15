/*
 * Memory pool allocator API.
 *
 * Each pool manages an independent contiguous memory region provided by
 * the caller.  No system heap allocation is used internally.
 */
#ifndef ALLOCATOR_H
#define ALLOCATOR_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Opaque pool handle — definition lives in allocator.c */
typedef struct mem_pool mem_pool_t;

/* ── Pool lifecycle ──────────────────────────────────────────────── */

/*
 * Create a pool backed by [region, region + region_size).
 * Returns NULL if the region is too small.
 */
mem_pool_t *pool_create(void *region, size_t region_size);

/* Invalidate the pool.  The caller owns the underlying region memory. */
void pool_destroy(mem_pool_t *pool);

/* ── Basic allocation ────────────────────────────────────────────── */

void *pool_malloc(mem_pool_t *pool, size_t size);
void  pool_free(mem_pool_t *pool, void *ptr);
void *pool_calloc(mem_pool_t *pool, size_t count, size_t size);

/*
 * Resize an allocation.  Must attempt in-place growth when possible
 * before falling back to alloc+copy+free.
 * ptr==NULL behaves like pool_malloc; new_size==0 behaves like pool_free.
 */
void *pool_realloc(mem_pool_t *pool, void *ptr, size_t new_size);

/* ── Aligned allocation ──────────────────────────────────────────── */

/*
 * Return memory aligned to `alignment` (must be a power of two, <= 4096).
 * The caller MUST use pool_aligned_free (not pool_free) to release it.
 */
void *pool_aligned_malloc(mem_pool_t *pool, size_t alignment, size_t size);
void  pool_aligned_free(mem_pool_t *pool, void *ptr);

/* ── Statistics ──────────────────────────────────────────────────── */

typedef struct {
    size_t total_size;          /* pool data capacity (set at creation)     */
    size_t used_size;           /* bytes currently allocated to callers     */
    size_t free_size;           /* bytes available for allocation           */
    size_t num_allocations;     /* lifetime successful allocation count     */
    size_t num_frees;           /* lifetime successful free count           */
    size_t largest_free_block;  /* largest contiguous free region (bytes)   */
    size_t num_free_blocks;     /* number of discrete free regions          */
    double fragmentation;       /* 1 - largest_free / free_size (0 if 0)   */
} pool_stats_t;

/* Fill *stats.  Returns 0 on success, -1 on invalid arguments. */
int pool_get_stats(mem_pool_t *pool, pool_stats_t *stats);

/* ── Thread safety ───────────────────────────────────────────────── */

/*
 * Install lock/unlock callbacks.  Every public pool_* function will call
 * lock_fn(ctx) on entry and unlock_fn(ctx) on exit when set.
 * Returns 0 on success.
 */
int pool_set_lock(mem_pool_t *pool,
                  void (*lock_fn)(void *ctx),
                  void (*unlock_fn)(void *ctx),
                  void *ctx);

#ifdef __cplusplus
}
#endif

#endif /* ALLOCATOR_H */
