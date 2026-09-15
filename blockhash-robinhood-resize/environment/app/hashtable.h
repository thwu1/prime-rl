/*
 *
 * Cache-Line-Aligned Hash Table with Incremental Resizing
 * Public API — do not modify this file.
 */

#ifndef BLOCK_HASH_TABLE_H
#define BLOCK_HASH_TABLE_H

#include <stdint.h>
#include <stddef.h>

/* Opaque handle */
typedef struct bht bht_t;

/*
 * Create a hash table. initial_capacity is a hint for the number of slots;
 * the actual capacity will be rounded up to a power of two (minimum 16).
 * Returns NULL on allocation failure.
 */
bht_t *bht_create(uint32_t initial_capacity);

/* Destroy the hash table and free all associated memory. */
void bht_destroy(bht_t *ht);

/*
 * Insert or update a key-value pair.
 *   key/key_len   — arbitrary byte sequence (key_len >= 1)
 *   value/value_len — arbitrary byte sequence (value_len >= 0)
 * Returns 0 on success, -1 on error.
 * If the key already exists, the value is replaced (count unchanged).
 */
int bht_insert(bht_t *ht, const void *key, uint32_t key_len,
               const void *value, uint32_t value_len);

/*
 * Look up a key.
 * On success (returns 0):
 *   *value_out points to internal storage containing the value.
 *   *value_len_out is set to the value's length.
 *   The pointer is valid until the next mutating operation on ht.
 * On failure (returns -1): key not found.
 */
int bht_lookup(bht_t *ht, const void *key, uint32_t key_len,
               void **value_out, uint32_t *value_len_out);

/*
 * Delete a key.
 * Returns 0 on success, -1 if the key was not found.
 */
int bht_delete(bht_t *ht, const void *key, uint32_t key_len);

/* Return the number of key-value pairs stored. */
uint64_t bht_count(bht_t *ht);

/* Return the current load factor (count / total_slots). */
double bht_load_factor(bht_t *ht);

/*
 * Return total memory consumption in bytes.
 * Includes block arrays, key-value data, and struct overhead.
 */
uint64_t bht_memory_usage(bht_t *ht);

/*
 * Return 1 if the table is currently performing an incremental resize
 * (i.e. two internal tables coexist), 0 otherwise.
 */
int bht_is_resizing(bht_t *ht);

/*
 * Return the mean probe distance across all stored entries.
 * Probe distance = number of slots an entry is displaced from its home slot.
 */
double bht_avg_probe_distance(bht_t *ht);

/*
 * Return 1 if every internal block array is aligned to a 64-byte
 * cache-line boundary, 0 otherwise.
 */
int bht_verify_alignment(bht_t *ht);

#endif /* BLOCK_HASH_TABLE_H */
