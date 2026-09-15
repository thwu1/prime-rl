 *
 * Multi-pool first-fit free-list memory allocator.
 */

#include "allocator.h"
#include "linkedlist/ll.h"
#include <stdint.h>
#include <string.h>

/* ── helpers ─────────────────────────────────────────────────────── */

#ifndef align_up
#define align_up(num, align) (((num) + ((align) - 1)) & ~((align) - 1))
#endif

typedef struct {
    ll_t   node;
    size_t size;
    char   block[];          /* flexible array – user data starts here */
} alloc_node_t;

#define ALLOC_HEADER_SZ  offsetof(alloc_node_t, block)
#define MIN_ALLOC_SZ     (ALLOC_HEADER_SZ + sizeof(void *))

typedef uint16_t offset_t;
#define PTR_OFFSET_SZ    sizeof(offset_t)

/* ── pool metadata (lives at the start of the caller's region) ─── */

struct mem_pool {
    ll_t      free_list;
    size_t    total_size;
    size_t    used_size;
    size_t    num_allocations;
    size_t    num_frees;
    void    (*lock_fn)(void *);
    void    (*unlock_fn)(void *);
    void     *lock_ctx;
    uintptr_t region_end;
};

/* ── internal lock wrappers ──────────────────────────────────────── */

static inline void pool_lock(mem_pool_t *pool)
{
    if (pool->lock_fn) pool->lock_fn(pool->lock_ctx);
}

static inline void pool_unlock(mem_pool_t *pool)
{
    if (pool->unlock_fn) pool->unlock_fn(pool->lock_ctx);
}

/* ── insert a free block in address order ────────────────────────── */

static void insert_free_block(mem_pool_t *pool, alloc_node_t *block)
{
    alloc_node_t *fb;
    list_for_each_entry(fb, &pool->free_list, node)
    {
        if (fb > block) {
            list_insert(&block->node, fb->node.prev, &fb->node);
            return;
        }
    }
    list_add_tail(&block->node, &pool->free_list);
}

/* ── coalesce adjacent free blocks ───────────────────────────────── */

static void defrag_free_list(mem_pool_t *pool)
{
    alloc_node_t *block, *last = NULL, *tmp;

    list_for_each_entry_safe(block, tmp, &pool->free_list, node)
    {
        if (last) {
            if (((uintptr_t)&last->block + last->size) == (uintptr_t)block) {
                last->size += ALLOC_HEADER_SZ + block->size;
                list_del(&block->node);
                continue;               /* keep trying with enlarged last */
            }
        }
        last = block;
    }
}

/* ── public API ──────────────────────────────────────────────────── */

mem_pool_t *pool_create(void *region, size_t region_size)
{
    if (!region ||
        region_size < sizeof(mem_pool_t) + ALLOC_HEADER_SZ + sizeof(void *))
        return NULL;

    mem_pool_t *pool =
        (mem_pool_t *)align_up((uintptr_t)region, sizeof(void *));
    memset(pool, 0, sizeof(*pool));
    list_init(&pool->free_list);

    uintptr_t blk_start =
        align_up((uintptr_t)pool + sizeof(mem_pool_t), sizeof(void *));
    uintptr_t end = (uintptr_t)region + region_size;

    if (blk_start + ALLOC_HEADER_SZ >= end)
        return NULL;

    alloc_node_t *first = (alloc_node_t *)blk_start;
    first->size = end - blk_start - ALLOC_HEADER_SZ;

    pool->total_size = first->size;
    pool->region_end = end;

    list_add(&first->node, &pool->free_list);
    return pool;
}

void pool_destroy(mem_pool_t *pool)
{
    if (pool) list_init(&pool->free_list);
}

void *pool_malloc(mem_pool_t *pool, size_t size)
{
    if (!pool || size == 0) return NULL;

    size = align_up(size, sizeof(void *));
    pool_lock(pool);

    void         *ptr   = NULL;
    alloc_node_t *found = NULL;

    list_for_each_entry(found, &pool->free_list, node)
    {
        if (found->size >= size) {
            ptr = &found->block;
            break;
        }
    }

    if (ptr) {
        /* split when remainder is useful */
        if ((found->size - size) >= MIN_ALLOC_SZ) {
            alloc_node_t *rest =
                (alloc_node_t *)((uintptr_t)&found->block + size);
            rest->size  = found->size - size - ALLOC_HEADER_SZ;
            found->size = size;
            list_insert(&rest->node, &found->node, found->node.next);
        }
        list_del(&found->node);
        pool->used_size += found->size;
        pool->num_allocations++;
    }

    pool_unlock(pool);
    return ptr;
}

void pool_free(mem_pool_t *pool, void *ptr)
{
    if (!pool || !ptr) return;

    alloc_node_t *block = container_of(ptr, alloc_node_t, block);

    pool_lock(pool);

    pool->used_size -= block->size;
    pool->num_frees++;

    insert_free_block(pool, block);
    defrag_free_list(pool);

    pool_unlock(pool);
}

void *pool_calloc(mem_pool_t *pool, size_t count, size_t size)
{
    if (!pool || count == 0 || size == 0) return NULL;

    size_t total = count * size;
    if (total / count != size) return NULL;   /* overflow */

    void *ptr = pool_malloc(pool, total);
    if (ptr) memset(ptr, 0, total);
    return ptr;
}

void *pool_realloc(mem_pool_t *pool, void *ptr, size_t new_size)
{
    if (!ptr)  return pool_malloc(pool, new_size);
    if (!pool) return NULL;
    if (new_size == 0) { pool_free(pool, ptr); return NULL; }

    alloc_node_t *block   = container_of(ptr, alloc_node_t, block);
    size_t        old_sz  = block->size;
    size_t        aligned = align_up(new_size, sizeof(void *));

    pool_lock(pool);

    /* ── shrink ─────────────────────────────────────────────────── */
    if (aligned <= block->size) {
        if ((block->size - aligned) >= MIN_ALLOC_SZ) {
            alloc_node_t *rem =
                (alloc_node_t *)((uintptr_t)&block->block + aligned);
            rem->size = block->size - aligned - ALLOC_HEADER_SZ;
            pool->used_size -= (block->size - aligned);
            block->size = aligned;
            insert_free_block(pool, rem);
            defrag_free_list(pool);
        }
        pool_unlock(pool);
        return ptr;
    }

    /* ── try in-place growth ────────────────────────────────────── */
    {
        size_t        needed   = aligned - block->size;
        alloc_node_t *next_blk =
            (alloc_node_t *)((uintptr_t)&block->block + block->size);

        if ((uintptr_t)next_blk + ALLOC_HEADER_SZ <= pool->region_end) {
            alloc_node_t *fb;
            list_for_each_entry(fb, &pool->free_list, node)
            {
                if (fb == next_blk &&
                    (fb->size + ALLOC_HEADER_SZ) >= needed) {
                    list_del(&fb->node);
                    size_t absorbed = ALLOC_HEADER_SZ + fb->size;
                    pool->used_size += absorbed;
                    block->size     += absorbed;

                    /* split excess */
                    if ((block->size - aligned) >= MIN_ALLOC_SZ) {
                        alloc_node_t *rem = (alloc_node_t *)(
                            (uintptr_t)&block->block + aligned);
                        rem->size = block->size - aligned - ALLOC_HEADER_SZ;
                        pool->used_size -= (block->size - aligned);
                        block->size = aligned;
                        insert_free_block(pool, rem);
                        defrag_free_list(pool);
                    }
                    pool_unlock(pool);
                    return ptr;
                }
                if (fb > next_blk) break;   /* list is address-sorted */
            }
        }
    }

    pool_unlock(pool);

    /* ── fallback: alloc + copy + free ──────────────────────────── */
    void *new_ptr = pool_malloc(pool, new_size);
    if (!new_ptr) return NULL;
    memcpy(new_ptr, ptr, old_sz < new_size ? old_sz : new_size);
    pool_free(pool, ptr);
    return new_ptr;
}

/* ── aligned allocation ──────────────────────────────────────────── */

void *pool_aligned_malloc(mem_pool_t *pool, size_t alignment, size_t size)
{
    if (!pool || size == 0 || alignment == 0) return NULL;
    if ((alignment & (alignment - 1)) != 0)  return NULL;  /* not pow2 */

    size_t hdr_extra = PTR_OFFSET_SZ + (alignment - 1);
    if (size + hdr_extra < size) return NULL;               /* overflow */

    void *base = pool_malloc(pool, size + hdr_extra);
    if (!base) return NULL;

    void *al = (void *)align_up((uintptr_t)base + PTR_OFFSET_SZ, alignment);
    *((offset_t *)al - 1) =
        (offset_t)((uintptr_t)al - (uintptr_t)base);

    return al;
}

void pool_aligned_free(mem_pool_t *pool, void *ptr)
{
    if (!pool || !ptr) return;
    offset_t off  = *((offset_t *)ptr - 1);
    void    *base = (void *)((uint8_t *)ptr - off);
    pool_free(pool, base);
}

/* ── statistics ──────────────────────────────────────────────────── */

int pool_get_stats(mem_pool_t *pool, pool_stats_t *stats)
{
    if (!pool || !stats) return -1;

    pool_lock(pool);

    stats->total_size      = pool->total_size;
    stats->used_size       = pool->used_size;
    stats->num_allocations = pool->num_allocations;
    stats->num_frees       = pool->num_frees;

    size_t free_sz = 0, largest = 0, cnt = 0;
    alloc_node_t *fb;
    list_for_each_entry(fb, &pool->free_list, node)
    {
        cnt++;
        free_sz += fb->size;
        if (fb->size > largest) largest = fb->size;
    }

    stats->free_size          = free_sz;
    stats->largest_free_block = largest;
    stats->num_free_blocks    = cnt;
    stats->fragmentation      = (free_sz > 0 && cnt > 0)
        ? 1.0 - ((double)largest / (double)free_sz)
        : 0.0;

    pool_unlock(pool);
    return 0;
}

/* ── locking ─────────────────────────────────────────────────────── */

int pool_set_lock(mem_pool_t *pool,
                  void (*lock_fn)(void *),
                  void (*unlock_fn)(void *),
                  void *ctx)
{
    if (!pool) return -1;
    pool->lock_fn   = lock_fn;
    pool->unlock_fn = unlock_fn;
    pool->lock_ctx  = ctx;
    return 0;
}
