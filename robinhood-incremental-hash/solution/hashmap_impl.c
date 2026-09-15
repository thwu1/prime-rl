/*
 *
 * Robin-hood hash table with incremental resizing.
 */
#include "hashmap.h"
#include <stdlib.h>
#include <string.h>

/* ------------------------------------------------------------------ */
/* Tunables                                                           */
/* ------------------------------------------------------------------ */
#define LOAD_FACTOR_HIGH 0.7
#define MIN_CAP          16

/* ------------------------------------------------------------------ */
/* Internal types                                                     */
/* ------------------------------------------------------------------ */
typedef struct {
    uint64_t hash;
    void    *key;
    void    *val;
    uint32_t klen;
    uint32_t vlen;
    uint8_t  used;
} slot_t;

struct hashmap {
    slot_t *tbl;          /* primary (new) table                       */
    size_t  cap;          /* capacity of primary table (power of 2)    */
    size_t  cnt;          /* total entry count across both tables      */

    /* Incremental-resize bookkeeping */
    slot_t *old_tbl;      /* old table being drained; NULL when idle   */
    size_t  old_cap;
    size_t  mig_cur;      /* scan cursor into old_tbl                  */
    size_t  mig_rem;      /* occupied entries still in old_tbl         */
};

/* ------------------------------------------------------------------ */
/* FNV-1a  (64-bit)                                                   */
/* ------------------------------------------------------------------ */
static uint64_t hash_bytes(const void *data, size_t len)
{
    const uint8_t *p = (const uint8_t *)data;
    uint64_t h = 0xcbf29ce484222325ULL;
    for (size_t i = 0; i < len; i++) {
        h ^= p[i];
        h *= 0x100000001b3ULL;
    }
    return h;
}

/* ------------------------------------------------------------------ */
/* Displacement (distance from ideal slot)                            */
/* ------------------------------------------------------------------ */
static inline size_t slot_disp(const slot_t *tbl, size_t cap, size_t pos)
{
    return (pos - (tbl[pos].hash & (cap - 1))) & (cap - 1);
}

/* ------------------------------------------------------------------ */
/* Find key in a single table.  Returns 0 + *out on hit, -1 on miss. */
/* ------------------------------------------------------------------ */
static int find_slot(slot_t *tbl, size_t cap, uint64_t h,
                     const void *key, size_t klen, size_t *out)
{
    size_t mask = cap - 1;
    size_t pos  = h & mask;
    size_t d    = 0;

    while (tbl[pos].used) {
        size_t ed = slot_disp(tbl, cap, pos);
        if (ed < d) return -1;                   /* robin-hood early exit */
        if (tbl[pos].hash == h &&
            tbl[pos].klen == (uint32_t)klen &&
            memcmp(tbl[pos].key, key, klen) == 0) {
            *out = pos;
            return 0;
        }
        pos = (pos + 1) & mask;
        d++;
    }
    return -1;
}

/* ------------------------------------------------------------------ */
/* Robin-hood insert (raw – caller owns key/val memory)               */
/* ------------------------------------------------------------------ */
static void rh_insert(slot_t *tbl, size_t cap,
                      uint64_t h, void *key, uint32_t klen,
                      void *val, uint32_t vlen)
{
    size_t mask = cap - 1;
    size_t pos  = h & mask;

    slot_t incoming;
    incoming.hash = h;
    incoming.key  = key;
    incoming.val  = val;
    incoming.klen = klen;
    incoming.vlen = vlen;
    incoming.used = 1;

    size_t d = 0;
    for (;;) {
        if (!tbl[pos].used) {
            tbl[pos] = incoming;
            return;
        }
        size_t ed = slot_disp(tbl, cap, pos);
        if (d > ed) {                            /* steal from the rich */
            slot_t tmp  = tbl[pos];
            tbl[pos]    = incoming;
            incoming    = tmp;
            d           = ed;
        }
        pos = (pos + 1) & mask;
        d++;
    }
}

/* ------------------------------------------------------------------ */
/* Delete from a single table (backward-shift, no tombstones)         */
/* ------------------------------------------------------------------ */
static int del_from_tbl(slot_t *tbl, size_t cap,
                        uint64_t h, const void *key, size_t klen)
{
    size_t pos;
    if (find_slot(tbl, cap, h, key, klen, &pos) != 0) return -1;

    free(tbl[pos].key);
    free(tbl[pos].val);
    tbl[pos].used = 0;

    /* backward shift */
    size_t mask = cap - 1;
    size_t cur  = pos;
    size_t nxt  = (cur + 1) & mask;
    while (tbl[nxt].used && slot_disp(tbl, cap, nxt) > 0) {
        tbl[cur]      = tbl[nxt];
        tbl[nxt].used = 0;
        cur = nxt;
        nxt = (nxt + 1) & mask;
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/* Resize helpers                                                     */
/* ------------------------------------------------------------------ */
static void start_resize(hashmap_t *m)
{
    size_t ncap = m->cap * 2;
    slot_t *ns  = calloc(ncap, sizeof(slot_t));
    if (!ns) return;

    size_t rem = 0;
    for (size_t i = 0; i < m->cap; i++)
        if (m->tbl[i].used) rem++;

    m->old_tbl = m->tbl;
    m->old_cap = m->cap;
    m->tbl     = ns;
    m->cap     = ncap;
    m->mig_cur = 0;
    m->mig_rem = rem;
}

static void migrate_step(hashmap_t *m)
{
    if (!m->old_tbl) return;

    int moved = 0;
    while (moved < HM_RESIZE_BATCH && m->mig_cur < m->old_cap) {
        size_t p = m->mig_cur++;
        if (m->old_tbl[p].used) {
            rh_insert(m->tbl, m->cap,
                      m->old_tbl[p].hash,
                      m->old_tbl[p].key, m->old_tbl[p].klen,
                      m->old_tbl[p].val, m->old_tbl[p].vlen);
            m->old_tbl[p].used = 0;
            m->old_tbl[p].key  = NULL;
            m->old_tbl[p].val  = NULL;
            m->mig_rem--;
            moved++;
        }
    }
    if (m->mig_rem == 0) {
        free(m->old_tbl);
        m->old_tbl = NULL;
        m->old_cap = 0;
    }
}

/* ------------------------------------------------------------------ */
/* Public API                                                         */
/* ------------------------------------------------------------------ */

hashmap_t *hm_create(size_t initial_capacity)
{
    if (initial_capacity < MIN_CAP) initial_capacity = MIN_CAP;
    size_t cap = 1;
    while (cap < initial_capacity) cap <<= 1;

    hashmap_t *m = calloc(1, sizeof(*m));
    if (!m) return NULL;
    m->tbl = calloc(cap, sizeof(slot_t));
    if (!m->tbl) { free(m); return NULL; }
    m->cap = cap;
    return m;
}

void hm_destroy(hashmap_t *m)
{
    if (!m) return;
    for (size_t i = 0; i < m->cap; i++) {
        if (m->tbl[i].used) { free(m->tbl[i].key); free(m->tbl[i].val); }
    }
    free(m->tbl);
    if (m->old_tbl) {
        for (size_t i = 0; i < m->old_cap; i++) {
            if (m->old_tbl[i].used) {
                free(m->old_tbl[i].key);
                free(m->old_tbl[i].val);
            }
        }
        free(m->old_tbl);
    }
    free(m);
}

int hm_insert(hashmap_t *m, const void *key, size_t klen,
              const void *value, size_t vlen)
{
    if (!m || !key || klen == 0) return -1;

    migrate_step(m);

    uint64_t h = hash_bytes(key, klen);

    /* update in new table? */
    size_t pos;
    if (find_slot(m->tbl, m->cap, h, key, klen, &pos) == 0) {
        free(m->tbl[pos].val);
        void *v = NULL;
        if (vlen > 0) { v = malloc(vlen); if (!v) return -1; memcpy(v, value, vlen); }
        m->tbl[pos].val  = v;
        m->tbl[pos].vlen = (uint32_t)vlen;
        return 0;
    }

    /* update in old table? */
    if (m->old_tbl && find_slot(m->old_tbl, m->old_cap, h, key, klen, &pos) == 0) {
        free(m->old_tbl[pos].val);
        void *v = NULL;
        if (vlen > 0) { v = malloc(vlen); if (!v) return -1; memcpy(v, value, vlen); }
        m->old_tbl[pos].val  = v;
        m->old_tbl[pos].vlen = (uint32_t)vlen;
        return 0;
    }

    /* brand-new entry → insert into new table */
    void *k = malloc(klen);
    if (!k) return -1;
    memcpy(k, key, klen);
    void *v = NULL;
    if (vlen > 0) { v = malloc(vlen); if (!v) { free(k); return -1; } memcpy(v, value, vlen); }

    rh_insert(m->tbl, m->cap, h, k, (uint32_t)klen, v, (uint32_t)vlen);
    m->cnt++;

    /* start resize if needed (only when no resize already in progress) */
    if (!m->old_tbl && (double)m->cnt / (double)m->cap > LOAD_FACTOR_HIGH) {
        start_resize(m);
    }
    return 0;
}

int hm_lookup(hashmap_t *m, const void *key, size_t klen,
              const void **val_out, size_t *vlen_out)
{
    if (!m || !key || klen == 0) return -1;

    migrate_step(m);

    uint64_t h = hash_bytes(key, klen);
    size_t pos;

    if (find_slot(m->tbl, m->cap, h, key, klen, &pos) == 0) {
        if (val_out)  *val_out  = m->tbl[pos].val;
        if (vlen_out) *vlen_out = m->tbl[pos].vlen;
        return 0;
    }
    if (m->old_tbl && find_slot(m->old_tbl, m->old_cap, h, key, klen, &pos) == 0) {
        if (val_out)  *val_out  = m->old_tbl[pos].val;
        if (vlen_out) *vlen_out = m->old_tbl[pos].vlen;
        return 0;
    }
    return -1;
}

int hm_delete(hashmap_t *m, const void *key, size_t klen)
{
    if (!m || !key || klen == 0) return -1;

    migrate_step(m);

    uint64_t h = hash_bytes(key, klen);

    if (del_from_tbl(m->tbl, m->cap, h, key, klen) == 0) {
        m->cnt--;
        return 0;
    }
    if (m->old_tbl && del_from_tbl(m->old_tbl, m->old_cap, h, key, klen) == 0) {
        m->cnt--;
        m->mig_rem--;
        if (m->mig_rem == 0) {
            free(m->old_tbl);
            m->old_tbl = NULL;
            m->old_cap = 0;
        }
        return 0;
    }
    return -1;
}

void hm_stats(const hashmap_t *m, hm_stats_t *s)
{
    if (!m || !s) return;
    memset(s, 0, sizeof(*s));

    s->size             = m->cnt;
    s->capacity         = m->cap;
    s->resize_remaining = m->mig_rem;

    size_t td = 0, n = 0, md = 0;
    for (size_t i = 0; i < m->cap; i++) {
        if (m->tbl[i].used) {
            size_t d = slot_disp(m->tbl, m->cap, i);
            td += d; n++;
            if (d > md) md = d;
        }
    }
    if (m->old_tbl) {
        for (size_t i = 0; i < m->old_cap; i++) {
            if (m->old_tbl[i].used) {
                size_t d = slot_disp(m->old_tbl, m->old_cap, i);
                td += d; n++;
                if (d > md) md = d;
            }
        }
    }

    s->max_displacement = md;
    s->avg_displacement = n > 0 ? (double)td / (double)n : 0.0;

    /* approximate memory accounting */
    s->memory_bytes = sizeof(hashmap_t)
                    + m->cap * sizeof(slot_t)
                    + (m->old_tbl ? m->old_cap * sizeof(slot_t) : 0);
    for (size_t i = 0; i < m->cap; i++) {
        if (m->tbl[i].used)
            s->memory_bytes += m->tbl[i].klen + m->tbl[i].vlen;
    }
    if (m->old_tbl) {
        for (size_t i = 0; i < m->old_cap; i++) {
            if (m->old_tbl[i].used)
                s->memory_bytes += m->old_tbl[i].klen + m->old_tbl[i].vlen;
        }
    }
}

size_t hm_iterate(const hashmap_t *m, hm_iter_fn fn, void *ud)
{
    if (!m || !fn) return 0;
    size_t v = 0;

    for (size_t i = 0; i < m->cap; i++) {
        if (m->tbl[i].used) {
            v++;
            if (fn(m->tbl[i].key, m->tbl[i].klen,
                   m->tbl[i].val, m->tbl[i].vlen, ud) != 0)
                return v;
        }
    }
    if (m->old_tbl) {
        for (size_t i = 0; i < m->old_cap; i++) {
            if (m->old_tbl[i].used) {
                v++;
                if (fn(m->old_tbl[i].key, m->old_tbl[i].klen,
                       m->old_tbl[i].val, m->old_tbl[i].vlen, ud) != 0)
                    return v;
            }
        }
    }
    return v;
}
