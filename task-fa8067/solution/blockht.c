
#include "blockht.h"
#include <stdlib.h>
#include <string.h>

/* ------------------------------------------------------------------ */
/* Block layout                                                        */
/* ------------------------------------------------------------------ */

/*
 * Each 4096-byte block starts with a 16-byte header, followed by
 * packed record data.
 *
 * Block header (16 bytes):
 *   struct Block *next    (8)  -- overflow-chain pointer
 *   uint16_t num_records  (2)  -- records stored in this block
 *   uint16_t used_bytes   (2)  -- bytes consumed for record data
 *   uint32_t _pad         (4)
 *
 * Each record (variable length):
 *   uint16_t key_len
 *   uint16_t val_len
 *   uint8_t  key[key_len]
 *   uint8_t  val[val_len]
 */

typedef struct Block {
    struct Block *next;
    uint16_t num_records;
    uint16_t used_bytes;
    uint32_t _pad;
} Block;

_Static_assert(sizeof(Block) == 16, "Block header must be 16 bytes");

#define BHDR  ((uint32_t)sizeof(Block))          /* 16 */
#define DCAP  (BHT_BLOCK_SIZE - BHDR)            /* 4080 */

/* Per-record header inside the data area. */
typedef struct {
    uint16_t key_len;
    uint16_t val_len;
} RecHdr;

#define RHDR  ((uint32_t)sizeof(RecHdr))          /* 4 */

/* ------------------------------------------------------------------ */
/* Main table structure                                                */
/* ------------------------------------------------------------------ */

struct BlockHashTable {
    uint32_t total_slots;     /* always a power of 2                  */
    uint32_t active_slots;    /* <= total_slots                       */
    uint32_t rps;             /* records-per-slot threshold           */
    uint32_t total_records;
    int32_t  countdown;       /* inserts until next expansion step    */
    Block  **buckets;         /* one chain head per slot              */
};

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

static uint8_t *bdata(Block *b) { return (uint8_t *)b + BHDR; }

static RecHdr *rec_at(Block *b, uint16_t off) {
    return (RecHdr *)(bdata(b) + off);
}

static uint8_t *rec_key(RecHdr *r) { return (uint8_t *)r + RHDR; }
static uint8_t *rec_val(RecHdr *r) { return (uint8_t *)r + RHDR + r->key_len; }
static uint32_t rec_total(RecHdr *r) { return RHDR + r->key_len + r->val_len; }

/* FNV-1a (32-bit) */
static uint32_t fnv1a(const void *data, uint32_t len) {
    const uint8_t *p = (const uint8_t *)data;
    uint32_t h = 2166136261u;
    for (uint32_t i = 0; i < len; i++) {
        h ^= p[i];
        h *= 16777619u;
    }
    return h;
}

/* Larson slot computation */
static uint32_t calc_slot(uint32_t hash, uint32_t total, uint32_t active) {
    uint32_t s = hash % total;
    if (s >= active)
        s -= total / 2;
    return s;
}

static Block *alloc_block(void) {
    return (Block *)calloc(1, BHT_BLOCK_SIZE);
}

static int block_fits(Block *b, uint32_t need) {
    return (DCAP - b->used_bytes) >= need;
}

static void block_append(Block *b, const void *key, uint32_t klen,
                         const void *val, uint32_t vlen) {
    RecHdr *r = rec_at(b, b->used_bytes);
    r->key_len = (uint16_t)klen;
    r->val_len = (uint16_t)vlen;
    memcpy(rec_key(r), key, klen);
    memcpy(rec_val(r), val, vlen);
    b->used_bytes += (uint16_t)(RHDR + klen + vlen);
    b->num_records++;
}

static void block_remove(Block *b, uint16_t off) {
    RecHdr *r = rec_at(b, off);
    uint32_t sz  = rec_total(r);
    uint32_t tail = b->used_bytes - off - sz;
    if (tail > 0)
        memmove(bdata(b) + off, bdata(b) + off + sz, tail);
    b->used_bytes -= (uint16_t)sz;
    b->num_records--;
}

/* Find key in a chain of blocks; return block + offset, or NULL. */
static Block *chain_find(Block *head, const void *key, uint32_t klen,
                         uint16_t *out_off) {
    for (Block *b = head; b; b = b->next) {
        uint16_t off = 0;
        for (uint16_t i = 0; i < b->num_records; i++) {
            RecHdr *r = rec_at(b, off);
            if (r->key_len == (uint16_t)klen &&
                memcmp(rec_key(r), key, klen) == 0) {
                if (out_off) *out_off = off;
                return b;
            }
            off += (uint16_t)rec_total(r);
        }
    }
    return NULL;
}

/* Insert a record into a slot's chain, growing as needed. */
static void chain_put(Block *head, const void *key, uint32_t klen,
                      const void *val, uint32_t vlen) {
    uint32_t need = RHDR + klen + vlen;
    Block *b = head;
    while (!block_fits(b, need)) {
        if (!b->next)
            b->next = alloc_block();
        b = b->next;
    }
    block_append(b, key, klen, val, vlen);
}

/* Free empty overflow blocks (never the head). */
static void chain_gc(Block *head) {
    Block *prev = head;
    Block *cur  = head->next;
    while (cur) {
        if (cur->num_records == 0) {
            prev->next = cur->next;
            free(cur);
            cur = prev->next;
        } else {
            prev = cur;
            cur  = cur->next;
        }
    }
}

static void chain_free(Block *b) {
    while (b) {
        Block *n = b->next;
        free(b);
        b = n;
    }
}

/* ------------------------------------------------------------------ */
/* Expansion (Larson)                                                  */
/* ------------------------------------------------------------------ */

typedef struct { uint8_t *k; uint32_t kl; uint8_t *v; uint32_t vl; } TmpRec;

static void expand(BlockHashTable *ht) {
    /* Double the slot array if all slots are active. */
    if (ht->active_slots == ht->total_slots) {
        uint32_t nt = ht->total_slots * 2;
        Block **nb = (Block **)calloc(nt, sizeof(Block *));
        if (!nb) return;
        memcpy(nb, ht->buckets, ht->total_slots * sizeof(Block *));
        free(ht->buckets);
        ht->buckets    = nb;
        ht->total_slots = nt;
    }

    uint32_t new_s = ht->active_slots;
    uint32_t old_s = new_s - ht->total_slots / 2;

    if (!ht->buckets[new_s])
        ht->buckets[new_s] = alloc_block();

    ht->active_slots++;

    /* Collect records in old_s that now hash to new_s. */
    TmpRec *mv  = NULL;
    uint32_t nm = 0, cap = 0;

    for (Block *b = ht->buckets[old_s]; b; b = b->next) {
        uint16_t off = 0;
        for (uint16_t j = 0; j < b->num_records; j++) {
            RecHdr *r = rec_at(b, off);
            uint32_t h = fnv1a(rec_key(r), r->key_len);
            uint32_t target = calc_slot(h, ht->total_slots, ht->active_slots);
            if (target != old_s) {
                if (nm == cap) {
                    cap = cap ? cap * 2 : 32;
                    mv  = (TmpRec *)realloc(mv, cap * sizeof(TmpRec));
                }
                mv[nm].kl = r->key_len;
                mv[nm].vl = r->val_len;
                mv[nm].k  = (uint8_t *)malloc(r->key_len);
                mv[nm].v  = (uint8_t *)malloc(r->val_len);
                memcpy(mv[nm].k, rec_key(r), r->key_len);
                memcpy(mv[nm].v, rec_val(r), r->val_len);
                nm++;
            }
            off += (uint16_t)rec_total(r);
        }
    }

    /* Remove from old chain. */
    for (uint32_t i = 0; i < nm; i++) {
        uint16_t roff;
        Block *b = chain_find(ht->buckets[old_s], mv[i].k, mv[i].kl, &roff);
        if (b) block_remove(b, roff);
    }

    /* Insert into new chain. */
    for (uint32_t i = 0; i < nm; i++) {
        chain_put(ht->buckets[new_s], mv[i].k, mv[i].kl, mv[i].v, mv[i].vl);
        free(mv[i].k);
        free(mv[i].v);
    }
    free(mv);

    chain_gc(ht->buckets[old_s]);

    ht->countdown = (int32_t)ht->rps;
}

/* ------------------------------------------------------------------ */
/* Public API                                                          */
/* ------------------------------------------------------------------ */

BlockHashTable *bht_create(uint32_t initial_slots, uint32_t records_per_slot) {
    BlockHashTable *ht = (BlockHashTable *)calloc(1, sizeof(*ht));
    if (!ht) return NULL;

    uint32_t n = 2;                        /* minimum for Larson */
    while (n < initial_slots) n <<= 1;

    ht->total_slots  = n;
    ht->active_slots = n;
    ht->rps          = records_per_slot;
    ht->countdown    = (int32_t)(n * records_per_slot);

    ht->buckets = (Block **)calloc(n, sizeof(Block *));
    if (!ht->buckets) { free(ht); return NULL; }

    for (uint32_t i = 0; i < n; i++)
        ht->buckets[i] = alloc_block();

    return ht;
}

void bht_destroy(BlockHashTable *ht) {
    if (!ht) return;
    for (uint32_t i = 0; i < ht->total_slots; i++)
        if (ht->buckets[i]) chain_free(ht->buckets[i]);
    free(ht->buckets);
    free(ht);
}

int bht_insert(BlockHashTable *ht, const void *key, uint32_t key_len,
               const void *value, uint32_t value_len) {
    if (!ht || !key || !value) return -1;
    if (key_len > 0xFFFF || value_len > 0xFFFF) return -1;

    uint32_t need = RHDR + key_len + value_len;
    if (need > DCAP) return -1;

    uint32_t h    = fnv1a(key, key_len);
    uint32_t slot = calc_slot(h, ht->total_slots, ht->active_slots);
    int is_update = 0;

    /* Duplicate check. */
    uint16_t off;
    Block *found = chain_find(ht->buckets[slot], key, key_len, &off);
    if (found) {
        RecHdr *r = rec_at(found, off);
        if (r->val_len == (uint16_t)value_len) {
            /* Same size: update in place. */
            memcpy(rec_val(r), value, value_len);
            return 0;
        }
        /* Different size: remove, then re-add below. */
        block_remove(found, off);
        ht->total_records--;
        is_update = 1;
    }

    chain_put(ht->buckets[slot], key, key_len, value, value_len);
    ht->total_records++;

    if (!is_update) {
        ht->countdown--;
        if (ht->countdown <= 0)
            expand(ht);
    }

    return 0;
}

const void *bht_lookup(const BlockHashTable *ht, const void *key,
                       uint32_t key_len, uint32_t *value_len) {
    if (!ht || !key) return NULL;

    uint32_t h    = fnv1a(key, key_len);
    uint32_t slot = calc_slot(h, ht->total_slots, ht->active_slots);

    uint16_t off;
    Block *b = chain_find(ht->buckets[slot], key, key_len, &off);
    if (!b) return NULL;

    RecHdr *r = rec_at(b, off);
    if (value_len) *value_len = r->val_len;
    return rec_val(r);
}

int bht_delete(BlockHashTable *ht, const void *key, uint32_t key_len) {
    if (!ht || !key) return -1;

    uint32_t h    = fnv1a(key, key_len);
    uint32_t slot = calc_slot(h, ht->total_slots, ht->active_slots);

    uint16_t off;
    Block *b = chain_find(ht->buckets[slot], key, key_len, &off);
    if (!b) return -1;

    block_remove(b, off);
    ht->total_records--;
    chain_gc(ht->buckets[slot]);
    return 0;
}

void bht_stats(const BlockHashTable *ht, BHTStats *stats) {
    if (!ht || !stats) return;
    memset(stats, 0, sizeof(*stats));

    stats->total_slots   = ht->total_slots;
    stats->active_slots  = ht->active_slots;
    stats->total_records = ht->total_records;

    for (uint32_t i = 0; i < ht->total_slots; i++) {
        uint32_t chain_len = 0;
        for (Block *b = ht->buckets[i]; b; b = b->next) {
            stats->total_blocks++;
            chain_len++;
            uint16_t off = 0;
            for (uint16_t j = 0; j < b->num_records; j++) {
                RecHdr *r = rec_at(b, off);
                stats->total_data_bytes += r->key_len + r->val_len;
                off += (uint16_t)rec_total(r);
            }
        }
        if (chain_len > stats->max_probe_distance)
            stats->max_probe_distance = chain_len;
    }

    stats->total_allocated_bytes = (uint64_t)stats->total_blocks * BHT_BLOCK_SIZE;
}
