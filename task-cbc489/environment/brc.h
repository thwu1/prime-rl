/*
 * brc.h - Biased Reference Counting (PEP 703)
 *
 * Interface for a biased reference counting system as specified in
 * PEP 703 (Making the Global Interpreter Lock Optional in CPython).
 *
 * Key design principles:
 * - Each object has an "owning thread" (the thread that created it)
 * - The owning thread modifies ob_ref_local (fast path, relaxed atomics)
 * - Other threads modify ob_ref_shared (slow path, read-modify-write atomics)
 * - ob_ref_shared stores the count shifted left by BRC_SHARED_SHIFT bits;
 *   the low 2 bits encode the object's lifecycle state
 * - The shared count can be temporarily negative (imbalanced cross-thread ops)
 * - Objects progress through states: DEFAULT -> MERGED
 * - Deallocation is permitted only from DEFAULT (quick path) or MERGED state
 * - Immortal objects (ob_ref_local == UINT32_MAX) ignore all incref/decref
 *
 */

#ifndef BRC_H
#define BRC_H

#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif

#include <stdint.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <pthread.h>
#include <stdlib.h>

/* The shared reference count is stored shifted left by this many bits */
#define BRC_SHARED_SHIFT 2

/* Sentinel value indicating an immortal object */
#define BRC_IMMORTAL_REFCNT UINT32_MAX

/* Object lifecycle states (stored in the low 2 bits of ob_ref_shared) */
#define BRC_STATE_DEFAULT  0  /* 0b00 - initial; allows quick dealloc path   */
#define BRC_STATE_WEAKREFS 1  /* 0b01 - supports weakrefs / lock-free access */
#define BRC_STATE_QUEUED   2  /* 0b10 - merge requested by non-owning thread */
#define BRC_STATE_MERGED   3  /* 0b11 - unowned; only shared count matters   */
#define BRC_STATE_MASK     3  /* 0b11 */

/* Destructor callback type */
typedef void (*brc_destructor_fn)(void *data);

/* Allocation/deallocation statistics for testing and verification */
typedef struct {
    _Atomic(int64_t) alloc_count;
    _Atomic(int64_t) dealloc_count;
} BrcStats;

/*
 * Object header matching PEP 703's proposed PyObject layout.
 *
 * ob_tid:        Thread ID of the owning thread. Zero means unowned
 *                (object is in MERGED state or being freed).
 * ob_ref_local:  Local reference count. Only the owning thread may
 *                modify this field. Set to BRC_IMMORTAL_REFCNT for
 *                immortal objects.
 * ob_ref_shared: Shared reference count (bits 2..63) combined with
 *                lifecycle state (bits 0..1). Non-owning threads
 *                modify this field atomically. The count portion is
 *                stored shifted left by BRC_SHARED_SHIFT.
 * ob_mutex:      Per-object mutex for synchronization.
 * ob_dealloc:    Destructor called when the object is freed.
 * ob_data:       Opaque user data pointer.
 * ob_stats:      Optional statistics tracker.
 */
typedef struct BrcObject {
    _Atomic(uintptr_t) ob_tid;
    _Atomic(uint32_t)  ob_ref_local;
    _Atomic(int64_t)   ob_ref_shared;
    pthread_mutex_t    ob_mutex;
    brc_destructor_fn  ob_dealloc;
    void              *ob_data;
    BrcStats          *ob_stats;
} BrcObject;

/*
 * Return the calling thread's unique identifier.
 * Must return a non-zero value that is distinct across concurrently
 * active threads.
 */
uintptr_t brc_thread_id(void);

/*
 * Allocate and initialize a new BrcObject.
 *
 * The returned object is owned by the calling thread (ob_tid set),
 * has a local reference count of 1, shared reference count of 0,
 * and is in the DEFAULT state. The allocation is tracked via stats
 * if non-NULL.
 *
 * Returns NULL on allocation failure.
 */
BrcObject *brc_alloc(brc_destructor_fn dealloc, void *data, BrcStats *stats);

/*
 * Increment the reference count.
 *
 * If the object is immortal, this is a no-op.
 * If the calling thread is the owning thread, increment ob_ref_local.
 * Otherwise, atomically add (1 << BRC_SHARED_SHIFT) to ob_ref_shared.
 */
void brc_incref(BrcObject *op);

/*
 * Decrement the reference count; may trigger deallocation.
 *
 * If the object is immortal, this is a no-op.
 * If the calling thread is the owning thread, decrement ob_ref_local.
 *   When ob_ref_local reaches zero, handle the merge-or-dealloc decision:
 *   - If ob_ref_shared == 0: quick dealloc (DEFAULT state, no shared refs).
 *   - Otherwise: transition to MERGED state (CAS the state bits),
 *     clear ob_tid to 0, and dealloc only if the shared count is also zero.
 * If the calling thread is NOT the owner, atomically subtract
 *   (1 << BRC_SHARED_SHIFT) from ob_ref_shared. If the object is in
 *   MERGED state and the shared count reaches zero, deallocate.
 */
void brc_decref(BrcObject *op);

/*
 * Conditionally increment the reference count (for optimistic lock-free access).
 *
 * Returns true and increments the shared count if the object appears alive.
 * Returns false without modifying anything if the object appears dead
 * (refcount is zero or the object is being freed).
 *
 * Uses an atomic compare-and-swap loop on ob_ref_shared.
 * This is the equivalent of CPython's _Py_TRY_INCREF.
 */
bool brc_try_incref(BrcObject *op);

/*
 * Mark the object as immortal. After this call, brc_incref and
 * brc_decref become no-ops for this object.
 */
void brc_set_immortal(BrcObject *op);

/*
 * Return true if the object is immortal.
 */
bool brc_is_immortal(BrcObject *op);

/*
 * Return the current lifecycle state (low 2 bits of ob_ref_shared).
 * One of BRC_STATE_DEFAULT, BRC_STATE_WEAKREFS, BRC_STATE_QUEUED,
 * or BRC_STATE_MERGED.
 */
int brc_get_state(BrcObject *op);

/*
 * Return the effective total reference count for debugging/testing.
 *
 * For DEFAULT/WEAKREFS/QUEUED states: ob_ref_local + (ob_ref_shared >> SHIFT)
 * For MERGED state: ob_ref_shared >> SHIFT
 * For immortal objects: returns -1
 */
int64_t brc_get_refcount(BrcObject *op);

#endif /* BRC_H */
