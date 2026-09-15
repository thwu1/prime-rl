/*
 */

#ifndef HASHMAP_H
#define HASHMAP_H

#include <stdint.h>
#include <stddef.h>

/* Maximum entries migrated per mutating operation during table growth. */
#define HM_RESIZE_BATCH 8

/* Opaque handle. */
typedef struct hashmap hashmap_t;

/* Statistics snapshot. */
typedef struct {
    size_t size;              /* total entries across all internal storage    */
    size_t capacity;          /* slots in the primary table                   */
    size_t max_displacement;  /* largest probe displacement of any entry      */
    double avg_displacement;  /* mean probe displacement                      */
    size_t memory_bytes;      /* approximate total heap usage                 */
    size_t resize_remaining;  /* entries pending migration; 0 = not growing   */
} hm_stats_t;

/*
 * Create a hash map.  initial_capacity is rounded up to the next power of 2
 * (minimum 16).  Returns NULL on allocation failure.
 */
hashmap_t *hm_create(size_t initial_capacity);

/* Free every resource held by the map.  NULL-safe. */
void hm_destroy(hashmap_t *map);

/*
 * Insert or update.  Both key and value are copied into internal storage.
 * key must be non-NULL with key_len > 0.  value may be NULL iff val_len == 0.
 * Returns 0 on success, -1 on invalid arguments or allocation failure.
 */
int hm_insert(hashmap_t *map, const void *key, size_t key_len,
              const void *value, size_t val_len);

/*
 * Look up a key.  On hit (return 0) *value_out points into internal storage
 * (valid until the next mutation) and *val_len_out is set.
 * On miss, returns -1.  Either out-parameter may be NULL.
 */
int hm_lookup(hashmap_t *map, const void *key, size_t key_len,
              const void **value_out, size_t *val_len_out);

/* Delete a key.  Returns 0 on success, -1 if not found. */
int hm_delete(hashmap_t *map, const void *key, size_t key_len);

/* Fill *stats with a snapshot of current map metrics. */
void hm_stats(const hashmap_t *map, hm_stats_t *stats);

/* Iteration callback.  Return 0 to continue, non-zero to stop early. */
typedef int (*hm_iter_fn)(const void *key, size_t key_len,
                          const void *value, size_t val_len,
                          void *user_data);

/* Visit every entry.  Returns number of entries actually visited. */
size_t hm_iterate(const hashmap_t *map, hm_iter_fn fn, void *user_data);

#endif /* HASHMAP_H */
