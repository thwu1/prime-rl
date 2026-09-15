/*
 */
#include "hashmap.h"
#include <stdlib.h>
#include <string.h>

/* ------------------------------------------------------------------ */
/* Tunables                                                           */
/* ------------------------------------------------------------------ */
#define LOAD_FACTOR_HIGH 0.7
#define MIN_CAP          16

#define SLOT_EMPTY    0
#define SLOT_OCCUPIED 1
#define SLOT_DELETED  2

/* ------------------------------------------------------------------ */
/* Internal types                                                     */
/* ------------------------------------------------------------------ */
typedef struct {
    uint64_t hash;
    void    *key;
    void    *val;
    uint32_t klen;
    uint32_t vlen;
    uint8_t  state;
} slot_t;

struct hashmap {
    slot_t *tbl;
    size_t  cap;
    size_t  cnt;
    size_t  tombstones;
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
/* Find key in the table.  Returns 0 + *out on hit, -1 on miss.      */
/* ------------------------------------------------------------------ */
static int find_slot(slot_t *tbl, size_t cap, uint64_t h,
                     const void *key, size_t klen, size_t *out)
{
    size_t mask = cap - 1;
    size_t pos  = h & mask;

    for (size_t i = 0; i < cap; i++) {
        size_t p = (pos + i) & mask;
        if (tbl[p].state == SLOT_EMPTY)
            return -1;
        if (tbl[p].state == SLOT_OCCUPIED &&
            tbl[p].hash == h &&
            tbl[p].klen == (uint32_t)klen &&
            memcmp(tbl[p].key, key, klen) == 0) {
            *out = p;
            return 0;
        }
    }
    return -1;
}

/* ------------------------------------------------------------------ */
/* Resize – rehashes the entire table in one shot                     */
/* ------------------------------------------------------------------ */
static void full_resize(hashmap_t *m)
{
    size_t ncap = m->cap * 2;
    slot_t *ns  = calloc(ncap, sizeof(slot_t));
    if (!ns) return;

    size_t mask = ncap - 1;
    for (size_t i = 0; i < m->cap; i++) {
        if (m->tbl[i].state == SLOT_OCCUPIED) {
            size_t pos = m->tbl[i].hash & mask;
            while (ns[pos].state == SLOT_OCCUPIED)
                pos = (pos + 1) & mask;
            ns[pos]       = m->tbl[i];
            ns[pos].state = SLOT_OCCUPIED;
        }
    }
    free(m->tbl);
    m->tbl        = ns;
    m->cap        = ncap;
    m->tombstones = 0;
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
        if (m->tbl[i].state == SLOT_OCCUPIED) {
            free(m->tbl[i].key);
            free(m->tbl[i].val);
        }
    }
    free(m->tbl);
    free(m);
}

int hm_insert(hashmap_t *m, const void *key, size_t klen,
              const void *value, size_t vlen)
{
    if (!m || !key || klen == 0) return -1;

    uint64_t h = hash_bytes(key, klen);

    /* Check for existing key (update in place) */
    size_t pos;
    if (find_slot(m->tbl, m->cap, h, key, klen, &pos) == 0) {
        free(m->tbl[pos].val);
        void *v = NULL;
        if (vlen > 0) {
            v = malloc(vlen);
            if (!v) return -1;
            memcpy(v, value, vlen);
        }
        m->tbl[pos].val  = v;
        m->tbl[pos].vlen = (uint32_t)vlen;
        return 0;
    }

    /* Resize if load too high (tombstones count toward load) */
    if ((double)(m->cnt + m->tombstones + 1) / (double)m->cap > LOAD_FACTOR_HIGH)
        full_resize(m);

    /* Allocate key/value copies */
    void *k = malloc(klen);
    if (!k) return -1;
    memcpy(k, key, klen);
    void *v = NULL;
    if (vlen > 0) {
        v = malloc(vlen);
        if (!v) { free(k); return -1; }
        memcpy(v, value, vlen);
    }

    /* Find first available slot (EMPTY or DELETED) */
    size_t mask = m->cap - 1;
    pos = h & mask;
    while (m->tbl[pos].state == SLOT_OCCUPIED)
        pos = (pos + 1) & mask;

    if (m->tbl[pos].state == SLOT_DELETED)
        m->tombstones--;

    m->tbl[pos].hash  = h;
    m->tbl[pos].key   = k;
    m->tbl[pos].val   = v;
    m->tbl[pos].klen  = (uint32_t)klen;
    m->tbl[pos].vlen  = (uint32_t)vlen;
    m->tbl[pos].state = SLOT_OCCUPIED;
    m->cnt++;

    return 0;
}

int hm_lookup(hashmap_t *m, const void *key, size_t klen,
              const void **val_out, size_t *vlen_out)
{
    if (!m || !key || klen == 0) return -1;

    uint64_t h = hash_bytes(key, klen);
    size_t pos;
    if (find_slot(m->tbl, m->cap, h, key, klen, &pos) == 0) {
        if (val_out)  *val_out  = m->tbl[pos].val;
        if (vlen_out) *vlen_out = m->tbl[pos].vlen;
        return 0;
    }
    return -1;
}

int hm_delete(hashmap_t *m, const void *key, size_t klen)
{
    if (!m || !key || klen == 0) return -1;

    uint64_t h = hash_bytes(key, klen);
    size_t pos;
    if (find_slot(m->tbl, m->cap, h, key, klen, &pos) != 0)
        return -1;

    free(m->tbl[pos].key);
    free(m->tbl[pos].val);
    m->tbl[pos].key   = NULL;
    m->tbl[pos].val   = NULL;
    m->tbl[pos].state = SLOT_DELETED;
    m->cnt--;
    m->tombstones++;

    return 0;
}

void hm_stats(const hashmap_t *m, hm_stats_t *s)
{
    if (!m || !s) return;
    memset(s, 0, sizeof(*s));

    s->size             = m->cnt;
    s->capacity         = m->cap;
    s->resize_remaining = 0;

    size_t td = 0, n = 0, md = 0;
    size_t mask = m->cap - 1;
    for (size_t i = 0; i < m->cap; i++) {
        if (m->tbl[i].state == SLOT_OCCUPIED) {
            size_t ideal = m->tbl[i].hash & mask;
            size_t d     = (i - ideal) & mask;
            td += d;
            n++;
            if (d > md) md = d;
        }
    }

    s->max_displacement = md;
    s->avg_displacement = n > 0 ? (double)td / (double)n : 0.0;

    s->memory_bytes = sizeof(*m) + m->cap * sizeof(slot_t);
    for (size_t i = 0; i < m->cap; i++) {
        if (m->tbl[i].state == SLOT_OCCUPIED)
            s->memory_bytes += m->tbl[i].klen + m->tbl[i].vlen;
    }
}

size_t hm_iterate(const hashmap_t *m, hm_iter_fn fn, void *ud)
{
    if (!m || !fn) return 0;
    size_t v = 0;
    for (size_t i = 0; i < m->cap; i++) {
        if (m->tbl[i].state == SLOT_OCCUPIED) {
            v++;
            if (fn(m->tbl[i].key, m->tbl[i].klen,
                   m->tbl[i].val, m->tbl[i].vlen, ud) != 0)
                return v;
        }
    }
    return v;
}
