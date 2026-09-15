#ifndef BLOCK_HASHTABLE_H
#define BLOCK_HASHTABLE_H


#include <stddef.h>

/*
 * Block-based hash table for variable-length key-value records.
 *
 * Records are stored in fixed-size memory blocks (a "block pool").
 * The slot table uses open addressing.
 */
typedef struct block_hashtable block_hashtable_t;

/*
 * Create a block-based hash table.
 *   block_size:      fixed size in bytes of each memory block
 *   initial_blocks:  number of blocks to pre-allocate
 * Returns a pointer to the hash table, or NULL on failure.
 */
block_hashtable_t *bht_create(size_t block_size, size_t initial_blocks);

/*
 * Destroy the hash table and free all associated memory.
 */
void bht_destroy(block_hashtable_t *ht);

/*
 * Insert or update a key-value pair.
 *   key / key_len:       pointer and length of the key (1..4000 bytes)
 *   value / value_len:   pointer and length of the value (0..4000 bytes)
 * Returns 0 on success, -1 on error.
 * If the key already exists, its value is overwritten.
 */
int bht_insert(block_hashtable_t *ht, const void *key, size_t key_len,
               const void *value, size_t value_len);

/*
 * Look up a key.
 *   key / key_len:       pointer and length of the key to search for
 *   value_buf:           caller-provided buffer to receive the value
 *   value_buf_size:      size of value_buf in bytes
 *   value_len_out:       if non-NULL, receives the full value length
 * Copies min(value_len, value_buf_size) bytes into value_buf.
 * Returns 0 if found, -1 if not found.
 */
int bht_lookup(block_hashtable_t *ht, const void *key, size_t key_len,
               void *value_buf, size_t value_buf_size, size_t *value_len_out);

/*
 * Delete a key-value pair.
 * Returns 0 if deleted, -1 if the key was not found.
 */
int bht_delete(block_hashtable_t *ht, const void *key, size_t key_len);

/*
 * Return the number of key-value pairs currently stored.
 */
size_t bht_count(block_hashtable_t *ht);

/*
 * Return the number of allocated blocks in the block pool.
 */
size_t bht_block_count(block_hashtable_t *ht);

/*
 * Return the configured block size (as passed to bht_create).
 */
size_t bht_block_size(block_hashtable_t *ht);

/*
 * Return the maximum probe sequence length (PSL) across all occupied slots.
 * PSL measures how far an entry sits from its ideal (home) position.
 */
size_t bht_max_psl(block_hashtable_t *ht);

/*
 * Return 1 if an incremental resize is currently in progress, 0 otherwise.
 */
int bht_uses_incremental_resize(block_hashtable_t *ht);

#endif /* BLOCK_HASHTABLE_H */
