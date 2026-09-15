/*
 * gc.h -- Public API for a garbage collector with ephemeron support.
 *
 */

#ifndef GC_H
#define GC_H

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

/* ============================================================
 * Object Type Tags
 * ============================================================ */
#define GC_TYPE_PAIR      1
#define GC_TYPE_VECTOR    2
#define GC_TYPE_EPHEMERON 3
#define GC_TYPE_OPAQUE    4

/* ============================================================
 * Object Structures
 * ============================================================
 * Every GC-managed object starts with a gc_obj_t header.
 * The collector is non-moving: object addresses are stable
 * across collections.
 */

typedef struct gc_obj {
    uint32_t type;        /* One of GC_TYPE_* */
    uint32_t total_size;  /* Total object size in bytes, including header */
} gc_obj_t;

/* Pair (cons cell): two pointer fields. */
typedef struct {
    gc_obj_t hdr;
    gc_obj_t *car;
    gc_obj_t *cdr;
} gc_pair_t;

/* Vector: variable-length array of pointer slots. */
typedef struct {
    gc_obj_t hdr;
    size_t length;
    gc_obj_t *data[];  /* 'length' elements, initialized to NULL */
} gc_vector_t;

/* Ephemeron: conditional reference.
 *
 * Semantics (enforced by gc_collect):
 *   - The ephemeron does NOT keep its key alive.
 *   - If the key is reachable from roots (through ordinary object
 *     references, or through values of other resolved ephemerons),
 *     the value is kept alive.
 *   - If the key is not reachable, both key and value fields are
 *     set to NULL (the ephemeron is "broken").
 *   - Resolution must be consistent: if resolving one ephemeron
 *     causes another ephemeron's key to become reachable, that
 *     ephemeron must also resolve.
 */
typedef struct {
    gc_obj_t hdr;
    gc_obj_t *key;
    gc_obj_t *value;
} gc_ephemeron_t;

/* Opaque: byte buffer with no pointer fields. */
typedef struct {
    gc_obj_t hdr;
    size_t length;
    uint8_t data[];  /* 'length' bytes, initialized to zero */
} gc_opaque_t;

/* ============================================================
 * Heap Handle (opaque -- defined in gc.c)
 * ============================================================ */
typedef struct gc_heap gc_heap_t;

/* ============================================================
 * Statistics
 * ============================================================ */
typedef struct {
    size_t heap_capacity;           /* Max heap size (0 = unlimited) */
    size_t allocated_bytes;         /* Bytes currently in use        */
    size_t total_allocated;         /* Cumulative bytes allocated    */
    size_t total_freed;             /* Cumulative bytes freed        */
    size_t collection_count;        /* Number of GC cycles run       */
    size_t live_object_count;       /* Objects currently alive       */
    size_t ephemeron_count;         /* Live ephemerons (total)       */
    size_t broken_ephemeron_count;  /* Broken ephemerons             */
} gc_stats_t;

/* ============================================================
 * API
 * ============================================================ */

/*
 * Create a new heap.
 *   max_heap_bytes: upper limit on memory the collector may use
 *                   (0 = unlimited).
 * Returns NULL on failure.
 */
gc_heap_t *gc_heap_create(size_t max_heap_bytes);

/* Destroy the heap and free all managed memory. */
void gc_heap_destroy(gc_heap_t *heap);

/*
 * Push a root slot.  'slot' must point to a gc_obj_t* variable.
 * During gc_collect() the collector reads *slot; the caller may
 * update *slot freely between collections.
 * Roots are popped in strict LIFO order via gc_root_pop().
 */
void gc_root_push(gc_heap_t *heap, gc_obj_t **slot);

/* Pop the most recently pushed root. */
void gc_root_pop(gc_heap_t *heap);

/*
 * Allocation.
 * Each function may trigger a collection if the heap nears capacity.
 * Returns NULL on out-of-memory (after attempting collection).
 * All pointer fields are initialized to NULL; byte buffers to zero.
 */
gc_pair_t      *gc_alloc_pair(gc_heap_t *heap);
gc_vector_t    *gc_alloc_vector(gc_heap_t *heap, size_t length);
gc_ephemeron_t *gc_alloc_ephemeron(gc_heap_t *heap,
                                    gc_obj_t *key, gc_obj_t *value);
gc_opaque_t    *gc_alloc_opaque(gc_heap_t *heap, size_t length);

/*
 * Run a garbage-collection cycle.
 * Reclaims all objects not reachable from roots.
 * Ephemeron semantics (see gc_ephemeron_t) must be respected.
 */
void gc_collect(gc_heap_t *heap);

/* Return current heap statistics. */
gc_stats_t gc_get_stats(gc_heap_t *heap);

#endif /* GC_H */
