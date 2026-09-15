/*
 * gc.c — Mark-sweep garbage collector with ephemeron fixpoint resolution.
 *
 * Internal design:
 *   - Each allocation prepends a gc_meta_t header (invisible to the user)
 *     that carries the mark bit and a linked-list pointer.
 *   - All live objects are linked via gc_meta_t.next for sweep traversal.
 *   - Marking is iterative (explicit worklist) to avoid stack overflow.
 *   - Ephemerons are resolved in a fixpoint loop after the initial mark.
 *
 */

#include "gc.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

/* ================================================================
 * Internal metadata — prepended before every gc_obj_t
 * ================================================================ */
typedef struct gc_meta {
    struct gc_meta *next;   /* all-objects linked list */
    uint8_t         marked; /* 0 or 1 during collection */
} gc_meta_t;

/*
 * Layout in memory:
 *   [ gc_meta_t ][ gc_obj_t  ... type-specific payload ... ]
 *                ^— pointer returned to the user
 *
 * sizeof(gc_meta_t) is 16 on 64-bit (8 ptr + 1 byte + 7 pad),
 * so the gc_obj_t that follows is naturally aligned.
 */
#define OBJ_TO_META(obj)  ((gc_meta_t *)((char *)(obj) - sizeof(gc_meta_t)))
#define META_TO_OBJ(meta) ((gc_obj_t  *)((char *)(meta) + sizeof(gc_meta_t)))

/* ================================================================
 * Worklist for iterative marking
 * ================================================================ */
typedef struct {
    gc_obj_t **items;
    size_t     count;
    size_t     capacity;
} worklist_t;

static void wl_init(worklist_t *wl) { memset(wl, 0, sizeof *wl); }

static void wl_free(worklist_t *wl) { free(wl->items); }

static void wl_push(worklist_t *wl, gc_obj_t *obj) {
    if (wl->count >= wl->capacity) {
        wl->capacity = wl->capacity ? wl->capacity * 2 : 256;
        wl->items = realloc(wl->items, wl->capacity * sizeof(gc_obj_t *));
    }
    wl->items[wl->count++] = obj;
}

static gc_obj_t *wl_pop(worklist_t *wl) {
    return wl->count > 0 ? wl->items[--wl->count] : NULL;
}

/* ================================================================
 * Heap structure
 * ================================================================ */
struct gc_heap {
    gc_meta_t  *all_objects;   /* head of the all-objects list */
    gc_obj_t ***root_stack;    /* dynamic array of (gc_obj_t **) */
    size_t      root_count;
    size_t      root_capacity;
    size_t      max_heap_bytes;
    size_t      allocated_bytes;
    size_t      total_allocated;
    size_t      total_freed;
    size_t      collection_count;
};

/* ================================================================
 * Heap lifecycle
 * ================================================================ */

gc_heap_t *gc_heap_create(size_t max_heap_bytes) {
    gc_heap_t *h = calloc(1, sizeof(gc_heap_t));
    if (!h) return NULL;
    h->max_heap_bytes = max_heap_bytes;
    h->root_capacity  = 64;
    h->root_stack = calloc(h->root_capacity, sizeof(gc_obj_t **));
    if (!h->root_stack) { free(h); return NULL; }
    return h;
}

void gc_heap_destroy(gc_heap_t *heap) {
    if (!heap) return;
    gc_meta_t *m = heap->all_objects;
    while (m) {
        gc_meta_t *next = m->next;
        free(m);
        m = next;
    }
    free(heap->root_stack);
    free(heap);
}

/* ================================================================
 * Root management
 * ================================================================ */

void gc_root_push(gc_heap_t *heap, gc_obj_t **slot) {
    if (heap->root_count >= heap->root_capacity) {
        heap->root_capacity *= 2;
        heap->root_stack = realloc(heap->root_stack,
                                   heap->root_capacity * sizeof(gc_obj_t **));
    }
    heap->root_stack[heap->root_count++] = slot;
}

void gc_root_pop(gc_heap_t *heap) {
    if (heap->root_count > 0)
        heap->root_count--;
}

/* ================================================================
 * Allocation helpers
 * ================================================================ */

static void *gc_raw_alloc(gc_heap_t *heap, size_t obj_size) {
    size_t total = sizeof(gc_meta_t) + obj_size;

    /* Check heap limit — try collection first. */
    if (heap->max_heap_bytes > 0 &&
        heap->allocated_bytes + total > heap->max_heap_bytes) {
        gc_collect(heap);
        if (heap->allocated_bytes + total > heap->max_heap_bytes)
            return NULL;
    }

    gc_meta_t *meta = calloc(1, total);
    if (!meta) return NULL;

    meta->next         = heap->all_objects;
    heap->all_objects  = meta;

    gc_obj_t *obj   = META_TO_OBJ(meta);
    obj->total_size = (uint32_t)obj_size;

    heap->allocated_bytes += total;
    heap->total_allocated += total;

    return obj;
}

gc_pair_t *gc_alloc_pair(gc_heap_t *heap) {
    gc_pair_t *p = gc_raw_alloc(heap, sizeof(gc_pair_t));
    if (!p) return NULL;
    p->hdr.type = GC_TYPE_PAIR;
    /* car, cdr already zero from calloc */
    return p;
}

gc_vector_t *gc_alloc_vector(gc_heap_t *heap, size_t length) {
    size_t sz = sizeof(gc_vector_t) + length * sizeof(gc_obj_t *);
    gc_vector_t *v = gc_raw_alloc(heap, sz);
    if (!v) return NULL;
    v->hdr.type = GC_TYPE_VECTOR;
    v->length   = length;
    /* data[] already zero from calloc */
    return v;
}

gc_ephemeron_t *gc_alloc_ephemeron(gc_heap_t *heap,
                                    gc_obj_t *key, gc_obj_t *value) {
    gc_ephemeron_t *e = gc_raw_alloc(heap, sizeof(gc_ephemeron_t));
    if (!e) return NULL;
    e->hdr.type = GC_TYPE_EPHEMERON;
    e->key      = key;
    e->value    = value;
    return e;
}

gc_opaque_t *gc_alloc_opaque(gc_heap_t *heap, size_t length) {
    size_t sz = sizeof(gc_opaque_t) + length;
    gc_opaque_t *o = gc_raw_alloc(heap, sz);
    if (!o) return NULL;
    o->hdr.type = GC_TYPE_OPAQUE;
    o->length   = length;
    /* data[] already zero from calloc */
    return o;
}

/* ================================================================
 * Marking — iterative with worklist
 * ================================================================ */

/*
 * Try to mark 'obj'.  If it was already marked, return immediately.
 * Otherwise set the mark bit and push onto the worklist so that
 * trace_one() can visit its children.
 */
static void mark_one(gc_obj_t *obj, worklist_t *wl) {
    if (!obj) return;
    gc_meta_t *m = OBJ_TO_META(obj);
    if (m->marked) return;
    m->marked = 1;
    wl_push(wl, obj);
}

/*
 * Pop one object from the worklist and trace its non-ephemeron
 * pointer fields.  Ephemeron key/value are handled separately
 * by the fixpoint loop.
 */
static void trace_one(gc_obj_t *obj, worklist_t *wl) {
    switch (obj->type) {
    case GC_TYPE_PAIR: {
        gc_pair_t *p = (gc_pair_t *)obj;
        mark_one(p->car, wl);
        mark_one(p->cdr, wl);
        break;
    }
    case GC_TYPE_VECTOR: {
        gc_vector_t *v = (gc_vector_t *)obj;
        for (size_t i = 0; i < v->length; i++)
            mark_one(v->data[i], wl);
        break;
    }
    case GC_TYPE_EPHEMERON:
        /* Key and value are NOT traced here.
         * The fixpoint loop handles them. */
        break;
    case GC_TYPE_OPAQUE:
        /* No pointer fields. */
        break;
    default:
        break;
    }
}

/* Drain the worklist until empty. */
static void drain(worklist_t *wl) {
    gc_obj_t *obj;
    while ((obj = wl_pop(wl)) != NULL)
        trace_one(obj, wl);
}

/* ================================================================
 * Collection
 * ================================================================ */

void gc_collect(gc_heap_t *heap) {
    worklist_t wl;
    wl_init(&wl);

    /* ---- Phase 1: Mark from roots ---- */
    for (size_t i = 0; i < heap->root_count; i++) {
        gc_obj_t *root = *heap->root_stack[i];
        mark_one(root, &wl);
    }
    drain(&wl);

    /* ---- Phase 2: Ephemeron fixpoint ---- */
    int changed;
    do {
        changed = 0;
        for (gc_meta_t *m = heap->all_objects; m; m = m->next) {
            if (!m->marked) continue;

            gc_obj_t *obj = META_TO_OBJ(m);
            if (obj->type != GC_TYPE_EPHEMERON) continue;

            gc_ephemeron_t *e = (gc_ephemeron_t *)obj;
            if (!e->key) continue;               /* already broken */

            gc_meta_t *km = OBJ_TO_META(e->key);
            if (!km->marked) continue;            /* key not yet live */

            if (e->value) {
                gc_meta_t *vm = OBJ_TO_META(e->value);
                if (!vm->marked) {
                    mark_one(e->value, &wl);
                    drain(&wl);
                    changed = 1;
                }
            }
        }
    } while (changed);

    /* ---- Phase 3: Break dead ephemerons ---- */
    for (gc_meta_t *m = heap->all_objects; m; m = m->next) {
        if (!m->marked) continue;

        gc_obj_t *obj = META_TO_OBJ(m);
        if (obj->type != GC_TYPE_EPHEMERON) continue;

        gc_ephemeron_t *e = (gc_ephemeron_t *)obj;
        if (e->key != NULL && !OBJ_TO_META(e->key)->marked) {
            e->key   = NULL;
            e->value = NULL;
        }
    }

    /* ---- Phase 4: Sweep ---- */
    gc_meta_t **prev = &heap->all_objects;
    gc_meta_t  *cur  = heap->all_objects;
    while (cur) {
        if (cur->marked) {
            cur->marked = 0;          /* reset for next cycle */
            prev = &cur->next;
            cur  = cur->next;
        } else {
            gc_meta_t *dead = cur;
            *prev = cur->next;
            cur   = cur->next;

            gc_obj_t *obj = META_TO_OBJ(dead);
            size_t total  = sizeof(gc_meta_t) + obj->total_size;
            heap->allocated_bytes -= total;
            heap->total_freed     += total;
            free(dead);
        }
    }

    heap->collection_count++;
    wl_free(&wl);
}

/* ================================================================
 * Statistics
 * ================================================================ */

gc_stats_t gc_get_stats(gc_heap_t *heap) {
    gc_stats_t s;
    memset(&s, 0, sizeof s);

    s.heap_capacity    = heap->max_heap_bytes;
    s.allocated_bytes  = heap->allocated_bytes;
    s.total_allocated  = heap->total_allocated;
    s.total_freed      = heap->total_freed;
    s.collection_count = heap->collection_count;

    for (gc_meta_t *m = heap->all_objects; m; m = m->next) {
        s.live_object_count++;
        gc_obj_t *obj = META_TO_OBJ(m);
        if (obj->type == GC_TYPE_EPHEMERON) {
            s.ephemeron_count++;
            gc_ephemeron_t *e = (gc_ephemeron_t *)obj;
            if (e->key == NULL)
                s.broken_ephemeron_count++;
        }
    }

    return s;
}
