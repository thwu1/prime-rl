
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
/* Provided helpers — use these in your implementation                 */
/* ------------------------------------------------------------------ */

/* Pointer to the data area of a block (immediately after the header). */
static uint8_t *bdata(Block *b) { return (uint8_t *)b + BHDR; }

/* Get record header at byte offset 'off' within a block's data area. */
static RecHdr *rec_at(Block *b, uint16_t off) {
    return (RecHdr *)(bdata(b) + off);
}

/* Pointer to the key bytes of a record. */
static uint8_t *rec_key(RecHdr *r) { return (uint8_t *)r + RHDR; }

/* Pointer to the value bytes of a record. */
static uint8_t *rec_val(RecHdr *r) { return (uint8_t *)r + RHDR + r->key_len; }

/* Total bytes consumed by a record (header + key + value). */
static uint32_t rec_total(RecHdr *r) { return RHDR + r->key_len + r->val_len; }

/* FNV-1a (32-bit) hash function. */
static uint32_t fnv1a(const void *data, uint32_t len) {
    const uint8_t *p = (const uint8_t *)data;
    uint32_t h = 2166136261u;
    for (uint32_t i = 0; i < len; i++) {
        h ^= p[i];
        h *= 16777619u;
    }
    return h;
}

/*
 * Larson slot computation for incremental expansion.
 *
 * hash % total yields a candidate slot in [0, total).
 * If that slot is not yet active (>= active), fold it back by
 * subtracting total/2, mapping it to the partner slot that hasn't
 * been split yet.
 */
static uint32_t calc_slot(uint32_t hash, uint32_t total, uint32_t active) {
    uint32_t s = hash % total;
    if (s >= active)
        s -= total / 2;
    return s;
}

/* Allocate a zeroed 4096-byte block. */
static Block *alloc_block(void) {
    return (Block *)calloc(1, BHT_BLOCK_SIZE);
}

/* Check whether a block has room for 'need' more bytes of record data. */
static int block_fits(Block *b, uint32_t need) {
    return (DCAP - b->used_bytes) >= need;
}

/* ------------------------------------------------------------------ */
/* Implement everything below.                                         */
/* ------------------------------------------------------------------ */

BlockHashTable *bht_create(uint32_t initial_slots, uint32_t records_per_slot) {
    (void)initial_slots; (void)records_per_slot;
    return NULL;
}

void bht_destroy(BlockHashTable *ht) {
    (void)ht;
}

int bht_insert(BlockHashTable *ht, const void *key, uint32_t key_len,
               const void *value, uint32_t value_len) {
    (void)ht; (void)key; (void)key_len; (void)value; (void)value_len;
    return -1;
}

const void *bht_lookup(const BlockHashTable *ht, const void *key,
                       uint32_t key_len, uint32_t *value_len) {
    (void)ht; (void)key; (void)key_len; (void)value_len;
    return NULL;
}

int bht_delete(BlockHashTable *ht, const void *key, uint32_t key_len) {
    (void)ht; (void)key; (void)key_len;
    return -1;
}

void bht_stats(const BlockHashTable *ht, BHTStats *stats) {
    (void)ht; (void)stats;
}
