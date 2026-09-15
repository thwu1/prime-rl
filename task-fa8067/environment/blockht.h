
#ifndef BLOCKHT_H
#define BLOCKHT_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

/* Every block in the hash table is exactly this many bytes. */
#define BHT_BLOCK_SIZE 4096

/* Opaque handle. */
typedef struct BlockHashTable BlockHashTable;

/* Statistics snapshot. */
typedef struct {
    uint32_t total_slots;           /* current slot-array size (power of 2)   */
    uint32_t active_slots;          /* slots that have been activated so far   */
    uint32_t total_records;         /* live key-value pairs                    */
    uint32_t total_blocks;          /* allocated blocks across all slot chains */
    uint32_t max_probe_distance;    /* longest slot chain (# of blocks)        */
    uint64_t total_data_bytes;      /* sum of (key_len + value_len) over all records */
    uint64_t total_allocated_bytes; /* total_blocks * BHT_BLOCK_SIZE           */
} BHTStats;

/*
 * Create a new block-packed hash table.
 *   initial_slots    -- starting number of active slots (rounded up to power of 2, min 2)
 *   records_per_slot -- expansion threshold per slot
 * Returns NULL on allocation failure.
 */
BlockHashTable *bht_create(uint32_t initial_slots, uint32_t records_per_slot);

/* Destroy and free all memory associated with the table. */
void bht_destroy(BlockHashTable *ht);

/*
 * Insert or update a variable-length key-value pair.
 * If the key already exists, the value is replaced.
 * Returns 0 on success, -1 on failure (e.g. record too large for a block).
 */
int bht_insert(BlockHashTable *ht, const void *key, uint32_t key_len,
               const void *value, uint32_t value_len);

/*
 * Look up a key.  On success, sets *value_len and returns a pointer to the
 * value data (valid until the next insert or delete).  Returns NULL if the
 * key is not found.
 */
const void *bht_lookup(const BlockHashTable *ht, const void *key,
                       uint32_t key_len, uint32_t *value_len);

/*
 * Delete a key-value pair.
 * Returns 0 on success, -1 if the key was not found.
 */
int bht_delete(BlockHashTable *ht, const void *key, uint32_t key_len);

/* Fill *stats with a consistent snapshot of the table's metrics. */
void bht_stats(const BlockHashTable *ht, BHTStats *stats);

#endif /* BLOCKHT_H */
