/*
 * brc_solution.c - Reference implementation of PEP 703 Biased Reference Counting
 *
 */

#include "brc.h"

/* ---- Thread identification ---- */

uintptr_t brc_thread_id(void) {
    return (uintptr_t)pthread_self();
}

/* ---- Internal deallocation ---- */

static void brc_dealloc_internal(BrcObject *op) {
    if (op->ob_stats) {
        atomic_fetch_add_explicit(&op->ob_stats->dealloc_count, 1,
                                  memory_order_relaxed);
    }
    if (op->ob_dealloc) {
        op->ob_dealloc(op->ob_data);
    }
    pthread_mutex_destroy(&op->ob_mutex);
    free(op);
}

/* Forward declarations for internal helpers */
static void brc_merge_zero_refcount(BrcObject *op);
static void brc_decref_shared(BrcObject *op);

/* ---- Allocation ---- */

BrcObject *brc_alloc(brc_destructor_fn dealloc, void *data, BrcStats *stats) {
    BrcObject *op = (BrcObject *)calloc(1, sizeof(BrcObject));
    if (!op) return NULL;

    atomic_init(&op->ob_tid, brc_thread_id());
    atomic_init(&op->ob_ref_local, (uint32_t)1);
    atomic_init(&op->ob_ref_shared, (int64_t)BRC_STATE_DEFAULT);
    pthread_mutex_init(&op->ob_mutex, NULL);
    op->ob_dealloc = dealloc;
    op->ob_data = data;
    op->ob_stats = stats;

    if (stats) {
        atomic_fetch_add_explicit(&stats->alloc_count, 1, memory_order_relaxed);
    }
    return op;
}

/* ---- Incref ---- */

void brc_incref(BrcObject *op) {
    uint32_t local = atomic_load_explicit(&op->ob_ref_local,
                                          memory_order_relaxed);
    if (local == BRC_IMMORTAL_REFCNT) return;  /* immortal */

    if (atomic_load_explicit(&op->ob_tid, memory_order_relaxed)
            == brc_thread_id()) {
        /* Owning thread fast path: relaxed local increment */
        atomic_store_explicit(&op->ob_ref_local, local + 1,
                              memory_order_relaxed);
    } else {
        /* Non-owning thread: atomic shared increment */
        atomic_fetch_add_explicit(&op->ob_ref_shared,
                                  (int64_t)1 << BRC_SHARED_SHIFT,
                                  memory_order_relaxed);
    }
}

/* ---- Decref ---- */

void brc_decref(BrcObject *op) {
    uint32_t local = atomic_load_explicit(&op->ob_ref_local,
                                          memory_order_relaxed);
    if (local == BRC_IMMORTAL_REFCNT) return;  /* immortal */

    if (atomic_load_explicit(&op->ob_tid, memory_order_relaxed)
            == brc_thread_id()) {
        /* Owning thread fast path */
        uint32_t new_local = local - 1;
        atomic_store_explicit(&op->ob_ref_local, new_local,
                              memory_order_relaxed);
        if (new_local == 0) {
            brc_merge_zero_refcount(op);
        }
    } else {
        /* Non-owning thread slow path */
        brc_decref_shared(op);
    }
}

/*
 * Called when the owning thread's local count reaches zero.
 *
 * If shared is also zero (DEFAULT state), do a quick dealloc.
 * Otherwise, transition to MERGED state via CAS, clear ownership,
 * and dealloc only if the shared count portion is also zero.
 */
static void brc_merge_zero_refcount(BrcObject *op) {
    int64_t shared = atomic_load_explicit(&op->ob_ref_shared,
                                          memory_order_acquire);

    if (shared == 0) {
        /* Quick dealloc: DEFAULT state, no shared references */
        atomic_store_explicit(&op->ob_tid, 0, memory_order_release);
        brc_dealloc_internal(op);
        return;
    }

    /* Transition state bits to MERGED using CAS loop */
    int64_t new_shared;
    do {
        new_shared = (shared & ~(int64_t)BRC_STATE_MASK) | BRC_STATE_MERGED;
    } while (!atomic_compare_exchange_weak_explicit(
        &op->ob_ref_shared, &shared, new_shared,
        memory_order_acq_rel, memory_order_acquire));

    /* Object is now unowned */
    atomic_store_explicit(&op->ob_tid, 0, memory_order_release);

    /* If shared count was zero at the CAS point, dealloc */
    if ((new_shared >> BRC_SHARED_SHIFT) == 0) {
        brc_dealloc_internal(op);
    }
}

/*
 * Shared decref path for non-owning threads.
 *
 * Atomically subtracts one count unit from ob_ref_shared.
 * If the object is in MERGED state and the count reaches zero,
 * triggers deallocation.
 */
static void brc_decref_shared(BrcObject *op) {
    int64_t old_shared = atomic_fetch_sub_explicit(
        &op->ob_ref_shared, (int64_t)1 << BRC_SHARED_SHIFT,
        memory_order_acq_rel);

    int64_t old_count = old_shared >> BRC_SHARED_SHIFT;
    int state = (int)(old_shared & BRC_STATE_MASK);

    /* Last shared reference in MERGED state -> dealloc */
    if (old_count == 1 && state == BRC_STATE_MERGED) {
        brc_dealloc_internal(op);
    }
}

/* ---- try_incref (conditional CAS increment) ---- */

bool brc_try_incref(BrcObject *op) {
    uint32_t local = atomic_load_explicit(&op->ob_ref_local,
                                          memory_order_acquire);
    if (local == BRC_IMMORTAL_REFCNT) return true;  /* always alive */

    int64_t shared = atomic_load_explicit(&op->ob_ref_shared,
                                          memory_order_acquire);

    for (;;) {
        int state = (int)(shared & BRC_STATE_MASK);
        int64_t count = shared >> BRC_SHARED_SHIFT;

        /* Determine if the object appears dead */
        if (state == BRC_STATE_MERGED && count <= 0) {
            return false;
        }
        if (state == BRC_STATE_DEFAULT) {
            local = atomic_load_explicit(&op->ob_ref_local,
                                         memory_order_acquire);
            if (local == 0 && count <= 0) {
                return false;
            }
        }

        /* Atomically increment the shared count */
        int64_t new_shared = shared + ((int64_t)1 << BRC_SHARED_SHIFT);
        if (atomic_compare_exchange_weak_explicit(
                &op->ob_ref_shared, &shared, new_shared,
                memory_order_acq_rel, memory_order_acquire)) {
            return true;
        }
        /* CAS failed - 'shared' has been reloaded by the CAS; retry */
    }
}

/* ---- Immortality ---- */

void brc_set_immortal(BrcObject *op) {
    atomic_store_explicit(&op->ob_ref_local, BRC_IMMORTAL_REFCNT,
                          memory_order_release);
}

bool brc_is_immortal(BrcObject *op) {
    return atomic_load_explicit(&op->ob_ref_local, memory_order_relaxed)
           == BRC_IMMORTAL_REFCNT;
}

/* ---- Introspection ---- */

int brc_get_state(BrcObject *op) {
    int64_t shared = atomic_load_explicit(&op->ob_ref_shared,
                                          memory_order_relaxed);
    return (int)(shared & BRC_STATE_MASK);
}

int64_t brc_get_refcount(BrcObject *op) {
    uint32_t local = atomic_load_explicit(&op->ob_ref_local,
                                          memory_order_relaxed);
    if (local == BRC_IMMORTAL_REFCNT) return -1;

    int64_t shared = atomic_load_explicit(&op->ob_ref_shared,
                                          memory_order_relaxed);
    int state = (int)(shared & BRC_STATE_MASK);
    int64_t count = shared >> BRC_SHARED_SHIFT;

    if (state == BRC_STATE_MERGED) return count;
    return (int64_t)local + count;
}
