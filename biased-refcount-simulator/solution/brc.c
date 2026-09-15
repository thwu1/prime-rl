/*
 * brc.c - Biased Reference Counting protocol implementation
 *
 */

#include <stdint.h>

#define BRC_SHARED_SHIFT     2
#define BRC_IMMORTAL_REFCNT  0xFFFFFFFFu

#define BRC_STATE_DEFAULT    0
#define BRC_STATE_WEAKREFS   1
#define BRC_STATE_QUEUED     2
#define BRC_STATE_MERGED     3

#define BRC_DEALLOC_NONE     0
#define BRC_DEALLOC_QUICK    1
#define BRC_DEALLOC_MERGED   2

/* Return codes from brc_decref */
#define BRC_DECREF_OK        0
#define BRC_DECREF_QUEUE     1

typedef struct {
    int64_t  ob_tid;
    uint32_t ob_ref_local;
    int64_t  ob_ref_shared;
    int32_t  deallocated;
    int32_t  dealloc_type;
    int32_t  state_transitions;
    int32_t  is_immortal;
} BRCObject;

static void _merge_zero_refcount(BRCObject *obj)
{
    if (obj->ob_ref_shared == 0) {
        obj->ob_tid = 0;
        obj->deallocated = 1;
        obj->dealloc_type = BRC_DEALLOC_QUICK;
    } else {
        int64_t total = (int64_t)obj->ob_ref_local
                      + (obj->ob_ref_shared >> BRC_SHARED_SHIFT);
        obj->ob_ref_shared = (total << BRC_SHARED_SHIFT) | BRC_STATE_MERGED;
        obj->state_transitions++;
        obj->ob_tid = 0;
        obj->ob_ref_local = 0;
        if (total == 0) {
            obj->deallocated = 1;
            obj->dealloc_type = BRC_DEALLOC_MERGED;
        }
    }
}

static int _decref_shared(BRCObject *obj)
{
    obj->ob_ref_shared -= (1LL << BRC_SHARED_SHIFT);
    int state = (int)(obj->ob_ref_shared & 0x3);
    int64_t sc = obj->ob_ref_shared >> BRC_SHARED_SHIFT;

    if (state == BRC_STATE_MERGED && sc == 0) {
        obj->deallocated = 1;
        obj->dealloc_type = BRC_DEALLOC_MERGED;
        return BRC_DECREF_OK;
    } else if (sc < 0 && state < BRC_STATE_QUEUED) {
        obj->ob_ref_shared = (obj->ob_ref_shared & ~0x3LL) | BRC_STATE_QUEUED;
        obj->state_transitions++;
        return BRC_DECREF_QUEUE;
    }
    return BRC_DECREF_OK;
}

void brc_init(BRCObject *obj, int64_t tid)
{
    obj->ob_tid = tid;
    obj->ob_ref_local = 1;
    obj->ob_ref_shared = 0;
    obj->deallocated = 0;
    obj->dealloc_type = BRC_DEALLOC_NONE;
    obj->state_transitions = 0;
    obj->is_immortal = 0;
}

void brc_incref(BRCObject *obj, int64_t current_tid)
{
    uint32_t new_local = obj->ob_ref_local + 1u;
    if (new_local == 0)
        return;  /* immortal: UINT32_MAX + 1 wraps to 0 */

    if (obj->ob_tid == current_tid)
        obj->ob_ref_local = new_local;
    else
        obj->ob_ref_shared += (1LL << BRC_SHARED_SHIFT);
}

int brc_decref(BRCObject *obj, int64_t current_tid)
{
    if (obj->ob_ref_local == BRC_IMMORTAL_REFCNT)
        return BRC_DECREF_OK;

    if (obj->ob_tid == current_tid) {
        obj->ob_ref_local--;
        if (obj->ob_ref_local == 0)
            _merge_zero_refcount(obj);
        return BRC_DECREF_OK;
    } else {
        return _decref_shared(obj);
    }
}

void brc_immortalize(BRCObject *obj)
{
    obj->ob_ref_local = BRC_IMMORTAL_REFCNT;
    obj->is_immortal = 1;
}

void brc_create_weakref(BRCObject *obj)
{
    if ((obj->ob_ref_shared & 0x3) == BRC_STATE_DEFAULT) {
        obj->ob_ref_shared = (obj->ob_ref_shared & ~0x3LL) | BRC_STATE_WEAKREFS;
        obj->state_transitions++;
    }
}

void brc_process_queued(BRCObject *obj)
{
    if (obj->deallocated)
        return;
    int64_t total = (int64_t)obj->ob_ref_local
                  + (obj->ob_ref_shared >> BRC_SHARED_SHIFT);
    obj->ob_ref_shared = (total << BRC_SHARED_SHIFT) | BRC_STATE_MERGED;
    obj->state_transitions++;
    obj->ob_tid = 0;
    obj->ob_ref_local = 0;
    if (total == 0) {
        obj->deallocated = 1;
        obj->dealloc_type = BRC_DEALLOC_MERGED;
    }
}
