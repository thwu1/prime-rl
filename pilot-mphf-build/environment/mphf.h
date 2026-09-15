#ifndef MPHF_H
#define MPHF_H

#include <stdint.h>
#include <stddef.h>

/* Opaque handle to a minimal perfect hash function. */
typedef struct mphf mphf_t;

/* Build an MPHF from an array of n distinct 64-bit keys.
 *   alpha  – load factor (0 < alpha < 1).
 *   lambda – average bucket size (> 0).
 * Returns NULL on failure. */
mphf_t *mphf_build(const uint64_t *keys, size_t n,
                    double alpha, double lambda);

/* Look up a key that was in the build set.
 * Returns a value in [0, n). Undefined for unknown keys. */
uint64_t mphf_query(const mphf_t *mf, uint64_t key);

/* Total space overhead of the data structure, in bits per key
 * (excludes the input keys themselves). */
double mphf_bits_per_key(const mphf_t *mf);

/* Serialize to a binary file. Returns 0 on success, -1 on error. */
int mphf_save(const mphf_t *mf, const char *path);

/* Deserialize from a binary file. Returns NULL on error. */
mphf_t *mphf_load(const char *path);

/* Free all memory associated with an MPHF instance. */
void mphf_free(mphf_t *mf);

/* ---- Decomposed statistics API ---- */

/* Return the number of keys stored in this MPHF. */
size_t mphf_key_count(const mphf_t *mf);

/* Return the storage size (bytes) of the pilot table component. */
size_t mphf_pilots_bytes(const mphf_t *mf);

/* Return the storage size (bytes) of the remap table component. */
size_t mphf_remap_bytes(const mphf_t *mf);

/* Return the number of keys whose primary slot is in the overflow
 * region and thus require remapping. */
size_t mphf_remap_count(const mphf_t *mf);

#endif /* MPHF_H */
