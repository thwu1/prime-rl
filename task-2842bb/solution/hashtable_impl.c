/*
 * Block-based hash table implementation.
 *
 */

#include "hashtable.h"
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

/* Visibility: compile with -fvisibility=hidden; public API gets default. */
#define BHT_API __attribute__((visibility("default")))

/* ---------- tunables ---------- */
#define RECORD_HDR   8            /* key_len(4) + val_len(4) */
#define LF_NUM       7            /* load-factor numerator   */
#define LF_DEN       10           /* load-factor denominator */
#define MIGRATE_BATCH 16
#define MIN_SLOTS     64

/* ---------- FNV-1a (32-bit) ---------- */
static uint32_t fnv1a(const uint8_t *p, size_t len) {
    uint32_t h = 2166136261u;
    for (size_t i = 0; i < len; i++) {
        h ^= p[i];
        h *= 16777619u;
    }
    return h;
}

/* ---------- internal types ---------- */
typedef struct { uint8_t *data; size_t used, cap; } block_t;

typedef struct {
    uint32_t bid;       /* block id              */
    uint32_t off;       /* byte offset in block  */
    uint32_t psl;       /* probe-sequence length */
    uint32_t hash;      /* cached hash           */
    int      occ;       /* 1 = occupied          */
} slot_t;

struct block_hashtable {
    slot_t  *slots;
    size_t   nslots;
    size_t   count;

    block_t *blocks;
    size_t   nblocks;
    size_t   bcap;
    size_t   bsize;          /* configured block size */

    /* incremental-resize state */
    slot_t  *old_slots;
    size_t   old_nslots;
    size_t   mig_pos;
    int      resizing;
};

/* ---------- block helpers ---------- */

static uint32_t alloc_block(block_hashtable_t *ht, size_t minsize) {
    if (ht->nblocks >= ht->bcap) {
        ht->bcap *= 2;
        ht->blocks = realloc(ht->blocks, ht->bcap * sizeof(block_t));
    }
    uint32_t id = (uint32_t)ht->nblocks++;
    size_t sz = minsize > ht->bsize ? minsize : ht->bsize;
    ht->blocks[id].data = calloc(1, sz);
    ht->blocks[id].used = 0;
    ht->blocks[id].cap  = sz;
    return id;
}

/* Try to append a record to a specific block.  Returns byte offset or -1. */
static int32_t block_append(block_t *b,
                             const void *key, size_t kl,
                             const void *val, size_t vl) {
    size_t need = RECORD_HDR + kl + vl;
    if (b->used + need > b->cap) return -1;
    uint32_t off = (uint32_t)b->used;
    uint32_t kl32 = (uint32_t)kl, vl32 = (uint32_t)vl;
    memcpy(b->data + off,     &kl32, 4);
    memcpy(b->data + off + 4, &vl32, 4);
    memcpy(b->data + off + RECORD_HDR,      key, kl);
    memcpy(b->data + off + RECORD_HDR + kl, val, vl);
    b->used += need;
    return (int32_t)off;
}

/* Store a record somewhere in the block pool. */
static void store_rec(block_hashtable_t *ht,
                      const void *key, size_t kl,
                      const void *val, size_t vl,
                      uint32_t *obid, uint32_t *ooff) {
    size_t need = RECORD_HDR + kl + vl;
    /* try the last block first */
    if (ht->nblocks > 0) {
        int32_t r = block_append(&ht->blocks[ht->nblocks - 1], key, kl, val, vl);
        if (r >= 0) { *obid = (uint32_t)(ht->nblocks - 1); *ooff = (uint32_t)r; return; }
    }
    uint32_t id = alloc_block(ht, need);
    int32_t  r  = block_append(&ht->blocks[id], key, kl, val, vl);
    *obid = id;
    *ooff = (uint32_t)r;
}

/* Read back key/value pointers from a stored record. */
static void read_rec(block_hashtable_t *ht, uint32_t bid, uint32_t off,
                     const void **kp, size_t *kl,
                     const void **vp, size_t *vl) {
    uint8_t *p = ht->blocks[bid].data + off;
    uint32_t k32, v32;
    memcpy(&k32, p,     4);
    memcpy(&v32, p + 4, 4);
    *kl = k32; *vl = v32;
    *kp = p + RECORD_HDR;
    *vp = p + RECORD_HDR + k32;
}

/* ---------- slot-level operations ---------- */

/* Robin-hood insert into a slot array. */
static void slot_insert(slot_t *s, size_t n,
                        uint32_t hash, uint32_t bid, uint32_t off) {
    size_t idx = hash % n;
    slot_t in;
    in.bid = bid; in.off = off; in.psl = 0; in.hash = hash; in.occ = 1;
    for (;;) {
        if (!s[idx].occ) { s[idx] = in; return; }
        if (in.psl > s[idx].psl) {
            slot_t tmp = s[idx]; s[idx] = in; in = tmp;
        }
        in.psl++;
        idx = (idx + 1) % n;
    }
}

/* Find a key in a slot array; return pointer to slot or NULL. */
static slot_t *slot_find(block_hashtable_t *ht,
                         slot_t *s, size_t n,
                         const void *key, size_t kl, uint32_t hash) {
    size_t idx = hash % n;
    uint32_t psl = 0;
    for (;;) {
        if (!s[idx].occ)       return NULL;
        if (psl > s[idx].psl)  return NULL;
        if (s[idx].hash == hash) {
            const void *sk, *sv; size_t skl, svl;
            read_rec(ht, s[idx].bid, s[idx].off, &sk, &skl, &sv, &svl);
            if (skl == kl && memcmp(sk, key, kl) == 0) return &s[idx];
        }
        psl++;
        idx = (idx + 1) % n;
    }
}

/* Delete a key from a slot array using backward-shift.
 * Returns 1 if deleted, 0 if not found. */
static int slot_del(block_hashtable_t *ht,
                    slot_t *s, size_t n,
                    const void *key, size_t kl, uint32_t hash) {
    size_t idx = hash % n;
    uint32_t psl = 0;
    for (;;) {
        if (!s[idx].occ)       return 0;
        if (psl > s[idx].psl)  return 0;
        if (s[idx].hash == hash) {
            const void *sk, *sv; size_t skl, svl;
            read_rec(ht, s[idx].bid, s[idx].off, &sk, &skl, &sv, &svl);
            if (skl == kl && memcmp(sk, key, kl) == 0) {
                /* found — backward-shift deletion */
                s[idx].occ = 0;
                size_t cur = idx, nxt = (cur + 1) % n;
                while (s[nxt].occ && s[nxt].psl > 0) {
                    s[cur] = s[nxt];
                    s[cur].psl--;
                    s[nxt].occ = 0;
                    cur = nxt;
                    nxt = (nxt + 1) % n;
                }
                return 1;
            }
        }
        psl++;
        idx = (idx + 1) % n;
    }
}

/* ---------- incremental resize ---------- */

static void migrate_batch(block_hashtable_t *ht) {
    if (!ht->resizing) return;
    int done = 0;
    while (ht->mig_pos < ht->old_nslots && done < MIGRATE_BATCH) {
        if (ht->old_slots[ht->mig_pos].occ) {
            slot_t *os = &ht->old_slots[ht->mig_pos];
            slot_insert(ht->slots, ht->nslots, os->hash, os->bid, os->off);
            os->occ = 0;
            done++;
        }
        ht->mig_pos++;
    }
    if (ht->mig_pos >= ht->old_nslots) {
        free(ht->old_slots);
        ht->old_slots  = NULL;
        ht->old_nslots = 0;
        ht->resizing   = 0;
    }
}

static void maybe_resize(block_hashtable_t *ht) {
    if (ht->resizing) return;
    if (ht->count * LF_DEN > ht->nslots * LF_NUM) {
        ht->old_slots  = ht->slots;
        ht->old_nslots = ht->nslots;
        ht->nslots    *= 2;
        ht->slots      = calloc(ht->nslots, sizeof(slot_t));
        ht->mig_pos    = 0;
        ht->resizing   = 1;
    }
}

/* ---------- public API ---------- */

BHT_API block_hashtable_t *bht_create(size_t block_size, size_t initial_blocks) {
    block_hashtable_t *ht = calloc(1, sizeof(*ht));
    if (!ht) return NULL;
    ht->bsize  = block_size;
    ht->nslots = MIN_SLOTS;
    ht->slots  = calloc(ht->nslots, sizeof(slot_t));
    ht->bcap   = initial_blocks < 4 ? 4 : initial_blocks;
    ht->blocks = calloc(ht->bcap, sizeof(block_t));
    for (size_t i = 0; i < initial_blocks; i++)
        alloc_block(ht, block_size);
    return ht;
}

BHT_API void bht_destroy(block_hashtable_t *ht) {
    if (!ht) return;
    for (size_t i = 0; i < ht->nblocks; i++) free(ht->blocks[i].data);
    free(ht->blocks);
    free(ht->slots);
    free(ht->old_slots);
    free(ht);
}

BHT_API int bht_insert(block_hashtable_t *ht, const void *key, size_t key_len,
               const void *value, size_t value_len) {
    if (!ht || !key || key_len == 0) return -1;
    migrate_batch(ht);

    uint32_t hash = fnv1a(key, key_len);

    /* check for existing key in new table -> update */
    slot_t *ex = slot_find(ht, ht->slots, ht->nslots, key, key_len, hash);
    if (ex) {
        uint32_t bid, off;
        store_rec(ht, key, key_len, value, value_len, &bid, &off);
        ex->bid = bid; ex->off = off;
        return 0;
    }

    /* during resize, check old table -> promote & update */
    if (ht->resizing) {
        ex = slot_find(ht, ht->old_slots, ht->old_nslots, key, key_len, hash);
        if (ex) {
            slot_del(ht, ht->old_slots, ht->old_nslots, key, key_len, hash);
            ht->count--;  /* will be re-incremented below */
        }
    }

    /* new insert */
    uint32_t bid, off;
    store_rec(ht, key, key_len, value, value_len, &bid, &off);
    slot_insert(ht->slots, ht->nslots, hash, bid, off);
    ht->count++;
    maybe_resize(ht);
    return 0;
}

BHT_API int bht_lookup(block_hashtable_t *ht, const void *key, size_t key_len,
               void *value_buf, size_t value_buf_size, size_t *value_len_out) {
    if (!ht || !key || key_len == 0) return -1;
    migrate_batch(ht);

    uint32_t hash = fnv1a(key, key_len);
    slot_t *f = slot_find(ht, ht->slots, ht->nslots, key, key_len, hash);
    if (!f && ht->resizing)
        f = slot_find(ht, ht->old_slots, ht->old_nslots, key, key_len, hash);
    if (!f) return -1;

    const void *sk, *sv; size_t skl, svl;
    read_rec(ht, f->bid, f->off, &sk, &skl, &sv, &svl);
    if (value_len_out) *value_len_out = svl;
    if (value_buf && value_buf_size > 0) {
        size_t cp = svl < value_buf_size ? svl : value_buf_size;
        memcpy(value_buf, sv, cp);
    }
    return 0;
}

BHT_API int bht_delete(block_hashtable_t *ht, const void *key, size_t key_len) {
    if (!ht || !key || key_len == 0) return -1;
    migrate_batch(ht);

    uint32_t hash = fnv1a(key, key_len);
    if (slot_del(ht, ht->slots, ht->nslots, key, key_len, hash)) {
        ht->count--;
        return 0;
    }
    if (ht->resizing &&
        slot_del(ht, ht->old_slots, ht->old_nslots, key, key_len, hash)) {
        ht->count--;
        return 0;
    }
    return -1;
}

BHT_API size_t bht_count(block_hashtable_t *ht)      { return ht ? ht->count   : 0; }
BHT_API size_t bht_block_count(block_hashtable_t *ht) { return ht ? ht->nblocks : 0; }
BHT_API size_t bht_block_size(block_hashtable_t *ht)  { return ht ? ht->bsize   : 0; }

BHT_API size_t bht_max_psl(block_hashtable_t *ht) {
    if (!ht) return 0;
    size_t mx = 0;
    for (size_t i = 0; i < ht->nslots; i++)
        if (ht->slots[i].occ && ht->slots[i].psl > mx) mx = ht->slots[i].psl;
    if (ht->resizing)
        for (size_t i = 0; i < ht->old_nslots; i++)
            if (ht->old_slots[i].occ && ht->old_slots[i].psl > mx)
                mx = ht->old_slots[i].psl;
    return mx;
}

BHT_API int bht_uses_incremental_resize(block_hashtable_t *ht) {
    return ht ? ht->resizing : 0;
}
