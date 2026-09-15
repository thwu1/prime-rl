/*
 *
 * Block-based Robin-Hood Hash Table with Incremental Resizing — solution.
 */

#include "hashtable.h"
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

/* ---------- constants ---------- */

#define CACHE_LINE       64
#define SLOTS_PER_BLOCK  4
#define RESIZE_NUM       3      /* threshold = 3/4 = 75% */
#define RESIZE_DEN       4
#define MIGRATE_PER_OP   16
#define FP_EMPTY         0

/* ---------- types ---------- */

typedef struct {
    uint8_t  fp;        /* fingerprint, 0 = empty */
    uint8_t  pdist;     /* probe distance from home slot */
    uint16_t klen;
    uint32_t vlen;
    void    *kv;        /* heap: key || value */
} slot_t;

typedef struct {
    slot_t slots[SLOTS_PER_BLOCK];
} __attribute__((aligned(CACHE_LINE))) block_t;

_Static_assert(sizeof(slot_t) == 16, "slot_t must be 16 bytes");
_Static_assert(sizeof(block_t) == CACHE_LINE, "block_t must equal one cache line");

typedef struct {
    block_t  *blocks;
    uint32_t  nslots;   /* always power of 2 */
    uint32_t  nblocks;
    uint64_t  count;
    uint64_t  kv_bytes; /* sum of (klen + vlen) for every entry */
} table_t;

struct bht {
    table_t  *pri;
    table_t  *sec;      /* non-NULL during incremental resize */
    uint32_t  mig_pos;  /* scan cursor in sec */
};

/* ---------- FNV-1a ---------- */

static uint64_t fnv1a(const void *data, uint32_t len) {
    const uint8_t *p = data;
    uint64_t h = 14695981039346656037ULL;
    for (uint32_t i = 0; i < len; i++) {
        h ^= p[i];
        h *= 1099511628211ULL;
    }
    return h;
}

static uint8_t fp_of(uint64_t h) {
    uint8_t f = (uint8_t)(h >> 56);
    return f ? f : 1;
}

/* ---------- power-of-two helpers ---------- */

static uint32_t next_p2(uint32_t v) {
    if (v < 16) v = 16;
    v--;
    v |= v >> 1; v |= v >> 2; v |= v >> 4;
    v |= v >> 8; v |= v >> 16;
    return v + 1;
}

/* ---------- table lifecycle ---------- */

static table_t *table_new(uint32_t min_slots) {
    table_t *t = calloc(1, sizeof(*t));
    if (!t) return NULL;
    t->nslots  = next_p2(min_slots);
    t->nblocks = t->nslots / SLOTS_PER_BLOCK;
    size_t sz  = (size_t)t->nblocks * sizeof(block_t);
    t->blocks  = aligned_alloc(CACHE_LINE, sz);
    if (!t->blocks) { free(t); return NULL; }
    memset(t->blocks, 0, sz);
    return t;
}

static void table_free(table_t *t) {
    if (!t) return;
    for (uint32_t i = 0; i < t->nslots; i++) {
        slot_t *s = &t->blocks[i / SLOTS_PER_BLOCK].slots[i % SLOTS_PER_BLOCK];
        if (s->fp != FP_EMPTY) free(s->kv);
    }
    free(t->blocks);
    free(t);
}

static inline slot_t *slot_at(table_t *t, uint32_t i) {
    return &t->blocks[i / SLOTS_PER_BLOCK].slots[i % SLOTS_PER_BLOCK];
}

static int keq(const slot_t *s, const void *key, uint32_t klen) {
    return s->klen == klen && memcmp(s->kv, key, klen) == 0;
}

/* ---------- single-table lookup ---------- */

static slot_t *tbl_find(table_t *t, const void *key, uint32_t klen, uint64_t h) {
    uint8_t  fp   = fp_of(h);
    uint32_t mask = t->nslots - 1;
    uint32_t idx  = (uint32_t)(h & mask);

    for (uint32_t d = 0; d < t->nslots; d++) {
        slot_t *s = slot_at(t, idx);
        if (s->fp == FP_EMPTY)   return NULL;
        if (s->pdist < d)        return NULL;  /* robin-hood early-exit */
        if (s->fp == fp && keq(s, key, klen))
            return s;
        idx = (idx + 1) & mask;
    }
    return NULL;
}

/* ---------- single-table insert ---------- */

static int tbl_insert(table_t *t, const void *key, uint32_t klen,
                      const void *val, uint32_t vlen, uint64_t h) {
    /* duplicate check */
    slot_t *exist = tbl_find(t, key, klen, h);
    if (exist) {
        size_t sz = (size_t)klen + vlen;
        void *nkv = malloc(sz ? sz : 1);
        if (!nkv) return -1;
        memcpy(nkv, key, klen);
        if (vlen) memcpy((char *)nkv + klen, val, vlen);
        t->kv_bytes -= exist->vlen;
        free(exist->kv);
        exist->kv   = nkv;
        exist->vlen = vlen;
        t->kv_bytes += vlen;
        return 0;
    }

    /* allocate kv for the new entry */
    size_t sz = (size_t)klen + vlen;
    void *kv  = malloc(sz ? sz : 1);
    if (!kv) return -1;
    memcpy(kv, key, klen);
    if (vlen) memcpy((char *)kv + klen, val, vlen);

    uint8_t  fp   = fp_of(h);
    uint32_t mask = t->nslots - 1;
    uint32_t idx  = (uint32_t)(h & mask);
    uint8_t  dist = 0;

    for (;;) {
        slot_t *s = slot_at(t, idx);

        if (s->fp == FP_EMPTY) {
            s->fp    = fp;
            s->pdist = dist;
            s->klen  = (uint16_t)klen;
            s->vlen  = vlen;
            s->kv    = kv;
            t->count++;
            t->kv_bytes += klen + vlen;
            return 0;
        }

        /* robin-hood: displace shorter probe distance */
        if (s->pdist < dist) {
            uint8_t  tf = s->fp;    s->fp    = fp;    fp   = tf;
            uint8_t  td = s->pdist; s->pdist = dist;  dist = td;
            uint16_t tk = s->klen;  s->klen  = (uint16_t)klen;  klen = tk;
            uint32_t tv = s->vlen;  s->vlen  = vlen;  vlen = tv;
            void    *tp = s->kv;    s->kv    = kv;    kv   = tp;
        }

        idx = (idx + 1) & mask;
        dist++;

        if (dist >= 250) {           /* safety bound */
            free(kv);
            return -1;
        }
    }
}

/* ---------- single-table delete (backward shift) ---------- */

static int tbl_delete(table_t *t, const void *key, uint32_t klen, uint64_t h) {
    uint8_t  fp   = fp_of(h);
    uint32_t mask = t->nslots - 1;
    uint32_t idx  = (uint32_t)(h & mask);

    for (uint32_t d = 0; d < t->nslots; d++) {
        slot_t *s = slot_at(t, idx);
        if (s->fp == FP_EMPTY) return -1;
        if (s->pdist < d)      return -1;

        if (s->fp == fp && keq(s, key, klen)) {
            t->kv_bytes -= ((uint64_t)s->klen + s->vlen);
            free(s->kv);
            t->count--;

            /* backward-shift: pull entries forward */
            uint32_t cur = idx;
            for (;;) {
                uint32_t nxt = (cur + 1) & mask;
                slot_t *ns = slot_at(t, nxt);
                if (ns->fp == FP_EMPTY || ns->pdist == 0) {
                    memset(slot_at(t, cur), 0, sizeof(slot_t));
                    break;
                }
                *slot_at(t, cur) = *ns;
                slot_at(t, cur)->pdist--;
                cur = nxt;
            }
            return 0;
        }
        idx = (idx + 1) & mask;
    }
    return -1;
}

/* ---------- incremental migration ---------- */

static void do_migrate(bht_t *ht) {
    if (!ht->sec) return;

    int exam = 0;
    while (exam < MIGRATE_PER_OP && ht->mig_pos < ht->sec->nslots) {
        slot_t *s = slot_at(ht->sec, ht->mig_pos);
        if (s->fp != FP_EMPTY) {
            uint64_t h = fnv1a(s->kv, s->klen);
            /* skip if user already (re-)inserted this key into primary */
            slot_t *in_pri = tbl_find(ht->pri, s->kv, s->klen, h);
            if (!in_pri) {
                int r = tbl_insert(ht->pri, s->kv, s->klen,
                                   (char *)s->kv + s->klen, s->vlen, h);
                if (r != 0) {
                    /* insertion failure: skip this slot, try later */
                    ht->mig_pos++;
                    exam++;
                    continue;
                }
            }
            ht->sec->kv_bytes -= ((uint64_t)s->klen + s->vlen);
            free(s->kv);
            s->fp = FP_EMPTY;
            s->kv = NULL;
            ht->sec->count--;
        }
        ht->mig_pos++;
        exam++;
    }

    /* check completion */
    if (ht->mig_pos >= ht->sec->nslots) {
        if (ht->sec->count == 0) {
            free(ht->sec->blocks);
            free(ht->sec);
            ht->sec     = NULL;
            ht->mig_pos = 0;
        } else {
            /* backward-shift deletion may have moved entries behind cursor */
            ht->mig_pos = 0;
        }
    }
}

static void maybe_resize(bht_t *ht) {
    if (ht->sec) return;
    if (ht->pri->count * RESIZE_DEN < (uint64_t)ht->pri->nslots * RESIZE_NUM)
        return;
    ht->sec     = ht->pri;
    ht->pri     = table_new(ht->sec->nslots * 2);
    ht->mig_pos = 0;
}

/* ---------- public API ---------- */

bht_t *bht_create(uint32_t cap) {
    bht_t *ht = calloc(1, sizeof(*ht));
    if (!ht) return NULL;
    ht->pri = table_new(cap);
    if (!ht->pri) { free(ht); return NULL; }
    return ht;
}

void bht_destroy(bht_t *ht) {
    if (!ht) return;
    table_free(ht->pri);
    table_free(ht->sec);
    free(ht);
}

int bht_insert(bht_t *ht, const void *key, uint32_t klen,
               const void *val, uint32_t vlen) {
    if (!ht || !key) return -1;
    uint64_t h = fnv1a(key, klen);

    /* remove stale copy from secondary to keep count accurate */
    if (ht->sec)
        tbl_delete(ht->sec, key, klen, h);   /* ignore -1 if not there */

    int ret = tbl_insert(ht->pri, key, klen, val, vlen, h);
    if (ret != 0) return ret;

    maybe_resize(ht);
    do_migrate(ht);
    return 0;
}

int bht_lookup(bht_t *ht, const void *key, uint32_t klen,
               void **vout, uint32_t *vlen_out) {
    if (!ht || !key) return -1;
    uint64_t h = fnv1a(key, klen);

    slot_t *s = tbl_find(ht->pri, key, klen, h);
    if (!s && ht->sec)
        s = tbl_find(ht->sec, key, klen, h);
    if (!s) return -1;

    if (vout)     *vout     = (char *)s->kv + s->klen;
    if (vlen_out) *vlen_out = s->vlen;
    return 0;
}

int bht_delete(bht_t *ht, const void *key, uint32_t klen) {
    if (!ht || !key) return -1;
    uint64_t h = fnv1a(key, klen);

    int ret = tbl_delete(ht->pri, key, klen, h);
    if (ret != 0 && ht->sec)
        ret = tbl_delete(ht->sec, key, klen, h);

    if (ret == 0)
        do_migrate(ht);
    return ret;
}

uint64_t bht_count(bht_t *ht) {
    if (!ht) return 0;
    uint64_t c = ht->pri->count;
    if (ht->sec) c += ht->sec->count;
    return c;
}

double bht_load_factor(bht_t *ht) {
    if (!ht) return 0.0;
    uint64_t cap = ht->pri->nslots;
    if (ht->sec) cap += ht->sec->nslots;
    return cap ? (double)bht_count(ht) / cap : 0.0;
}

uint64_t bht_memory_usage(bht_t *ht) {
    if (!ht) return 0;
    uint64_t m = sizeof(*ht);
    m += sizeof(table_t) + (uint64_t)ht->pri->nblocks * sizeof(block_t)
         + ht->pri->kv_bytes;
    if (ht->sec)
        m += sizeof(table_t) + (uint64_t)ht->sec->nblocks * sizeof(block_t)
             + ht->sec->kv_bytes;
    return m;
}

int bht_is_resizing(bht_t *ht) {
    return ht && ht->sec != NULL;
}

double bht_avg_probe_distance(bht_t *ht) {
    if (!ht) return 0.0;
    uint64_t td = 0, te = 0;
    for (uint32_t i = 0; i < ht->pri->nslots; i++) {
        slot_t *s = slot_at(ht->pri, i);
        if (s->fp) { td += s->pdist; te++; }
    }
    if (ht->sec) {
        for (uint32_t i = 0; i < ht->sec->nslots; i++) {
            slot_t *s = slot_at(ht->sec, i);
            if (s->fp) { td += s->pdist; te++; }
        }
    }
    return te ? (double)td / te : 0.0;
}

int bht_verify_alignment(bht_t *ht) {
    if (!ht) return 0;
    if ((uintptr_t)ht->pri->blocks % CACHE_LINE) return 0;
    for (uint32_t i = 0; i < ht->pri->nblocks; i++)
        if ((uintptr_t)&ht->pri->blocks[i] % CACHE_LINE) return 0;
    if (ht->sec) {
        if ((uintptr_t)ht->sec->blocks % CACHE_LINE) return 0;
        for (uint32_t i = 0; i < ht->sec->nblocks; i++)
            if ((uintptr_t)&ht->sec->blocks[i] % CACHE_LINE) return 0;
    }
    return 1;
}
