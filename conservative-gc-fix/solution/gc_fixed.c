/*
 * mini_gc.c - Fixed conservative mark-sweep garbage collector.
 *
 * Fixes applied:
 *   1. find_block   — interior pointer support
 *   2. drain_mark_stack — full scan range (no off-by-one)
 *   3. gc_collect   — correct phase ordering
 *   4. process_dlinks — implemented
 *   5. finalization — topological ordering with cycle detection
 *   6. sweep       — adjacent free block coalescing
 */

#include "gc.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <sys/mman.h>


/* ---------- Configuration ---------- */
#define GC_ALIGN_TO       sizeof(void *)
#define GC_ALIGN(x)       (((x) + GC_ALIGN_TO - 1) & ~(GC_ALIGN_TO - 1))
#define GC_BLOCK_MAGIC    0x47434F42u
#define GC_MAX_ROOTS      256
#define GC_MAX_FINS       4096
#define GC_MAX_DLINKS     4096
#define GC_MARK_STACK_SZ  16384
#define GC_MIN_SPLIT      (GC_ALIGN_TO * 2)

/* ---------- Block header ---------- */
typedef struct block_hdr {
    uint32_t           magic;
    uint32_t           size;
    uint8_t            in_use;
    uint8_t            marked;
    uint8_t            atomic;
    uint8_t            has_fin;
    struct block_hdr  *next_free;
} block_hdr_t;

#define HEADER_SIZE   GC_ALIGN(sizeof(block_hdr_t))
#define HDR_TO_OBJ(h) ((void *)((char *)(h) + HEADER_SIZE))
#define OBJ_TO_HDR(o) ((block_hdr_t *)((char *)(o) - HEADER_SIZE))

/* ---------- Finalizer entry ---------- */
typedef struct {
    void           *obj;
    gc_finalizer_fn fn;
    void           *client_data;
    int             active;
} fin_entry_t;

/* ---------- Disappearing link entry ---------- */
typedef struct {
    void **link;
    int    active;
} dlink_entry_t;

/* ---------- Root range ---------- */
typedef struct { void *lo, *hi; } root_range_t;

/* ---------- Queued finalizer (for deferred call) ---------- */
typedef struct {
    void           *obj;
    gc_finalizer_fn fn;
    void           *client_data;
} queued_fin_t;

/* ---------- Global GC state ---------- */
static struct {
    char         *heap;
    size_t        heap_size;
    block_hdr_t  *free_list;

    root_range_t  roots[GC_MAX_ROOTS];
    int           nroots;

    fin_entry_t   fins[GC_MAX_FINS];
    int           nfins;

    dlink_entry_t dlinks[GC_MAX_DLINKS];
    int           ndlinks;

    block_hdr_t  *mstack[GC_MARK_STACK_SZ];
    int           mtop;

    queued_fin_t  fqueue[GC_MAX_FINS];
    int           fqueue_len;

    size_t        collections;
    int           inited;
} G;

/* ================================================================
 *  Heap helpers
 * ================================================================ */

static int ptr_in_heap(const void *p) {
    return (const char *)p >= G.heap &&
           (const char *)p <  G.heap + G.heap_size;
}

/*
 * FIX 1: Interior pointer support.
 * Accept any pointer that falls within the user-data range
 * [obj_start, obj_start + size) of an in-use block.
 */
static block_hdr_t *find_block(const void *ptr) {
    char *p = G.heap;
    while (p + HEADER_SIZE <= G.heap + G.heap_size) {
        block_hdr_t *h = (block_hdr_t *)p;
        if (h->magic != GC_BLOCK_MAGIC) break;
        if (h->in_use) {
            char *obj = (char *)HDR_TO_OBJ(h);
            if ((const char *)ptr >= obj &&
                (const char *)ptr <  obj + h->size)
                return h;
        }
        p += HEADER_SIZE + h->size;
    }
    return NULL;
}

/* ================================================================
 *  Mark phase
 * ================================================================ */

static void mark_push(block_hdr_t *h) {
    if (G.mtop < GC_MARK_STACK_SZ)
        G.mstack[G.mtop++] = h;
}

static void mark_obj(block_hdr_t *h) {
    if (!h || h->marked) return;
    h->marked = 1;
    if (!h->atomic)
        mark_push(h);
}

static void scan_range(const char *lo, const char *hi) {
    const char *p;
    for (p = lo; p + sizeof(void *) <= hi; p += sizeof(void *)) {
        uintptr_t val;
        memcpy(&val, p, sizeof(val));
        if (ptr_in_heap((void *)val)) {
            block_hdr_t *h = find_block((void *)val);
            if (h && h->in_use)
                mark_obj(h);
        }
    }
}

/*
 * FIX 2: Scan the entire object (obj + sz), not (obj + sz - sizeof(void*)).
 */
static void drain_mark_stack(void) {
    while (G.mtop > 0) {
        block_hdr_t *h = G.mstack[--G.mtop];
        char *obj = (char *)HDR_TO_OBJ(h);
        uint32_t sz = h->size;
        if (sz >= sizeof(void *))
            scan_range(obj, obj + sz);
    }
}

static void mark_from_roots(void) {
    int i;
    for (i = 0; i < G.nroots; i++)
        scan_range((const char *)G.roots[i].lo,
                   (const char *)G.roots[i].hi);
    drain_mark_stack();
}

static void clear_all_marks(void) {
    char *p = G.heap;
    while (p + HEADER_SIZE <= G.heap + G.heap_size) {
        block_hdr_t *h = (block_hdr_t *)p;
        if (h->magic != GC_BLOCK_MAGIC) break;
        h->marked = 0;
        p += HEADER_SIZE + h->size;
    }
}

/* ================================================================
 *  FIX 4: Disappearing links — actually null them
 * ================================================================ */

static void process_dlinks(void) {
    int i;
    for (i = 0; i < G.ndlinks; i++) {
        void *target;
        block_hdr_t *h;
        if (!G.dlinks[i].active) continue;
        target = *(G.dlinks[i].link);
        if (!target || !ptr_in_heap(target)) continue;
        h = find_block(target);
        if (h && h->in_use && !h->marked) {
            *(G.dlinks[i].link) = NULL;
            G.dlinks[i].active = 0;
        }
    }
}

/* ================================================================
 *  FIX 5: Topological finalization with cycle detection
 * ================================================================ */

static void enqueue_and_mark_finalizers(void) {
    int  unreachable[GC_MAX_FINS];   /* indices into G.fins[] */
    block_hdr_t *uhdrs[GC_MAX_FINS];
    int  n_un = 0;
    int  i, j;
    char *adj;        /* n_un × n_un adjacency matrix */
    int  *in_deg;
    int  *topo;       /* topological order */
    int   topo_len;
    int  *queue;
    int   qf, qb;

    G.fqueue_len = 0;

    /* Step 1: collect unreachable finalizable objects */
    for (i = 0; i < G.nfins; i++) {
        block_hdr_t *h;
        if (!G.fins[i].active) continue;
        h = OBJ_TO_HDR(G.fins[i].obj);
        if (h->in_use && !h->marked) {
            unreachable[n_un] = i;
            uhdrs[n_un] = h;
            n_un++;
        }
    }
    if (n_un == 0) return;

    /* Step 2: build dependency graph.
       Edge i→j means object i points to object j, so i is finalized first. */
    adj    = (char *)calloc((size_t)n_un * (size_t)n_un, 1);
    in_deg = (int  *)calloc((size_t)n_un, sizeof(int));
    topo   = (int  *)malloc((size_t)n_un * sizeof(int));
    queue  = (int  *)malloc((size_t)n_un * sizeof(int));
    if (!adj || !in_deg || !topo || !queue) goto cleanup;

    for (i = 0; i < n_un; i++) {
        char *obj = (char *)HDR_TO_OBJ(uhdrs[i]);
        uint32_t sz = uhdrs[i]->size;
        const char *p;
        for (p = obj; p + sizeof(void *) <= obj + sz; p += sizeof(void *)) {
            uintptr_t val;
            block_hdr_t *target;
            memcpy(&val, p, sizeof(val));
            if (!ptr_in_heap((void *)val)) continue;
            target = find_block((void *)val);
            if (!target) continue;
            for (j = 0; j < n_un; j++) {
                if (j != i && uhdrs[j] == target) {
                    if (!adj[i * n_un + j]) {
                        adj[i * n_un + j] = 1;
                        in_deg[j]++;
                    }
                }
            }
        }
    }

    /* Step 3: Kahn's algorithm — topological sort + cycle detection */
    qf = qb = 0;
    topo_len = 0;
    for (i = 0; i < n_un; i++)
        if (in_deg[i] == 0) queue[qb++] = i;

    while (qf < qb) {
        int node = queue[qf++];
        topo[topo_len++] = node;
        for (j = 0; j < n_un; j++) {
            if (adj[node * n_un + j]) {
                in_deg[j]--;
                if (in_deg[j] == 0) queue[qb++] = j;
            }
        }
    }
    /* Nodes NOT in topo[] are in cycles — do not finalize them.  */

    /* Step 4: queue non-cyclic finalizers in topological order,
       mark them so they survive sweep. */
    for (i = 0; i < topo_len; i++) {
        int idx   = topo[i];
        int fidx  = unreachable[idx];
        block_hdr_t *h = uhdrs[idx];

        if (G.fqueue_len < GC_MAX_FINS) {
            G.fqueue[G.fqueue_len].obj         = G.fins[fidx].obj;
            G.fqueue[G.fqueue_len].fn          = G.fins[fidx].fn;
            G.fqueue[G.fqueue_len].client_data = G.fins[fidx].client_data;
            G.fqueue_len++;
        }
        G.fins[fidx].active = 0;
        h->has_fin = 0;

        /* Mark object and everything reachable from it. */
        mark_obj(h);
        drain_mark_stack();
    }

    /* Step 5: mark cyclic objects too (they leak but survive). */
    for (i = 0; i < n_un; i++) {
        int in_topo = 0;
        for (j = 0; j < topo_len; j++)
            if (topo[j] == i) { in_topo = 1; break; }
        if (!in_topo) {
            mark_obj(uhdrs[i]);
            drain_mark_stack();
        }
    }

cleanup:
    free(adj);
    free(in_deg);
    free(topo);
    free(queue);
}

static void call_queued_finalizers(void) {
    int i;
    for (i = 0; i < G.fqueue_len; i++)
        G.fqueue[i].fn(G.fqueue[i].obj, G.fqueue[i].client_data);
    G.fqueue_len = 0;
}

/* ================================================================
 *  FIX 6: Sweep with adjacent free block coalescing
 * ================================================================ */

static void sweep(void) {
    char *p = G.heap;
    G.free_list = NULL;

    while (p + HEADER_SIZE <= G.heap + G.heap_size) {
        block_hdr_t *h = (block_hdr_t *)p;
        if (h->magic != GC_BLOCK_MAGIC) break;

        if (h->in_use && !h->marked) {
            h->in_use  = 0;
            h->has_fin = 0;
            h->atomic  = 0;
            memset(HDR_TO_OBJ(h), 0, h->size);
        }

        /* Coalesce with following free blocks. */
        if (!h->in_use) {
            char *next = p + HEADER_SIZE + h->size;
            while (next + HEADER_SIZE <= G.heap + G.heap_size) {
                block_hdr_t *nh = (block_hdr_t *)next;
                if (nh->magic != GC_BLOCK_MAGIC) break;
                if (nh->in_use && !nh->marked) {
                    nh->in_use  = 0;
                    nh->has_fin = 0;
                    nh->atomic  = 0;
                    memset(HDR_TO_OBJ(nh), 0, nh->size);
                }
                if (nh->in_use) break;
                h->size += HEADER_SIZE + nh->size;
                memset(nh, 0, HEADER_SIZE);
                next = p + HEADER_SIZE + h->size;
            }
            h->next_free = G.free_list;
            G.free_list  = h;
        }

        p += HEADER_SIZE + h->size;
    }
}

/* ================================================================
 *  FIX 3: Correct collection phase ordering
 *
 *  mark → dlinks → finalize (topo, mark survivors) → sweep → call fins
 * ================================================================ */

void gc_collect(void) {
    if (!G.inited) return;
    clear_all_marks();
    mark_from_roots();
    process_dlinks();
    enqueue_and_mark_finalizers();
    sweep();
    call_queued_finalizers();
    G.collections++;
}

/* ================================================================
 *  Allocation
 * ================================================================ */

static block_hdr_t *alloc_from_free(size_t need) {
    block_hdr_t **pp = &G.free_list;
    while (*pp) {
        block_hdr_t *h = *pp;
        if (h->size >= need) {
            if (h->size >= need + HEADER_SIZE + GC_MIN_SPLIT) {
                char *rest_addr = (char *)h + HEADER_SIZE + need;
                block_hdr_t *rest = (block_hdr_t *)rest_addr;
                rest->magic     = GC_BLOCK_MAGIC;
                rest->size      = h->size - (uint32_t)need - HEADER_SIZE;
                rest->in_use    = 0;
                rest->marked    = 0;
                rest->atomic    = 0;
                rest->has_fin   = 0;
                rest->next_free = h->next_free;
                *pp = rest;
                h->size = (uint32_t)need;
            } else {
                *pp = h->next_free;
            }
            h->in_use    = 1;
            h->marked    = 0;
            h->atomic    = 0;
            h->has_fin   = 0;
            h->next_free = NULL;
            memset(HDR_TO_OBJ(h), 0, h->size);
            return h;
        }
        pp = &(*pp)->next_free;
    }
    return NULL;
}

static void *gc_alloc_internal(size_t size, int atomic) {
    size_t aligned;
    block_hdr_t *h;
    if (!G.inited) return NULL;
    aligned = GC_ALIGN(size < GC_MIN_SPLIT ? GC_MIN_SPLIT : size);
    h = alloc_from_free(aligned);
    if (!h) {
        gc_collect();
        h = alloc_from_free(aligned);
    }
    if (!h) return NULL;
    h->atomic = (uint8_t)atomic;
    return HDR_TO_OBJ(h);
}

void *gc_malloc(size_t size)        { return gc_alloc_internal(size, 0); }
void *gc_malloc_atomic(size_t size) { return gc_alloc_internal(size, 1); }

/* ================================================================
 *  Initialization / shutdown
 * ================================================================ */

int gc_init(size_t heap_size) {
    block_hdr_t *h;
    if (G.inited) return -1;
    heap_size = GC_ALIGN(heap_size);
    G.heap = (char *)mmap(NULL, heap_size, PROT_READ | PROT_WRITE,
                          MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (G.heap == MAP_FAILED) return -1;
    G.heap_size = heap_size;

    h = (block_hdr_t *)G.heap;
    h->magic     = GC_BLOCK_MAGIC;
    h->size      = (uint32_t)(heap_size - HEADER_SIZE);
    h->in_use    = 0;
    h->marked    = 0;
    h->atomic    = 0;
    h->has_fin   = 0;
    h->next_free = NULL;
    G.free_list  = h;

    G.nroots = G.nfins = G.ndlinks = G.mtop = 0;
    G.fqueue_len = 0;
    G.collections = 0;
    G.inited = 1;
    return 0;
}

void gc_shutdown(void) {
    if (!G.inited) return;
    munmap(G.heap, G.heap_size);
    memset(&G, 0, sizeof(G));
}

/* ================================================================
 *  Root registration
 * ================================================================ */

int gc_add_root(void *start, void *end) {
    if (G.nroots >= GC_MAX_ROOTS) return -1;
    G.roots[G.nroots].lo = start;
    G.roots[G.nroots].hi = end;
    G.nroots++;
    return 0;
}

/* ================================================================
 *  Finalizer registration
 * ================================================================ */

int gc_register_finalizer(void *obj, gc_finalizer_fn fn, void *client_data) {
    block_hdr_t *h;
    int i;
    if (!obj || !fn) return -1;
    if (!ptr_in_heap(obj)) return -1;
    h = OBJ_TO_HDR(obj);
    if (h->magic != GC_BLOCK_MAGIC || !h->in_use) return -1;

    for (i = 0; i < G.nfins; i++) {
        if (G.fins[i].active && G.fins[i].obj == obj) {
            G.fins[i].fn = fn;
            G.fins[i].client_data = client_data;
            return 0;
        }
    }
    for (i = 0; i < G.nfins; i++) {
        if (!G.fins[i].active) {
            G.fins[i].obj = obj;
            G.fins[i].fn  = fn;
            G.fins[i].client_data = client_data;
            G.fins[i].active = 1;
            h->has_fin = 1;
            return 0;
        }
    }
    if (G.nfins >= GC_MAX_FINS) return -1;
    G.fins[G.nfins].obj         = obj;
    G.fins[G.nfins].fn          = fn;
    G.fins[G.nfins].client_data = client_data;
    G.fins[G.nfins].active      = 1;
    h->has_fin = 1;
    G.nfins++;
    return 0;
}

/* ================================================================
 *  Disappearing link registration
 * ================================================================ */

int gc_register_disappearing_link(void **link) {
    int i;
    if (!link || !*link) return -1;
    for (i = 0; i < G.ndlinks; i++)
        if (G.dlinks[i].active && G.dlinks[i].link == link) return 0;
    for (i = 0; i < G.ndlinks; i++) {
        if (!G.dlinks[i].active) {
            G.dlinks[i].link   = link;
            G.dlinks[i].active = 1;
            return 0;
        }
    }
    if (G.ndlinks >= GC_MAX_DLINKS) return -1;
    G.dlinks[G.ndlinks].link   = link;
    G.dlinks[G.ndlinks].active = 1;
    G.ndlinks++;
    return 0;
}

int gc_unregister_disappearing_link(void **link) {
    int i;
    for (i = 0; i < G.ndlinks; i++) {
        if (G.dlinks[i].active && G.dlinks[i].link == link) {
            G.dlinks[i].active = 0;
            return 0;
        }
    }
    return -1;
}

/* ================================================================
 *  Statistics
 * ================================================================ */

size_t gc_collection_count(void) { return G.collections; }
size_t gc_heap_size(void)        { return G.heap_size; }

size_t gc_free_bytes(void) {
    size_t total = 0;
    block_hdr_t *h = G.free_list;
    while (h) { total += h->size; h = h->next_free; }
    return total;
}
