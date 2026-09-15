/*
 *
 * Counting Quotient Filter (CQF) — Public API
 *
 * A CQF is a compact probabilistic data structure supporting approximate
 * set membership with counting, deletion, merging, resizing, serialization,
 * and vector-space operations.
 *
 * Based on:
 *   "A General-Purpose Counting Filter: Making Every Bit Count"
 *   Pandey, Bender, Johnson, Patro — SIGMOD 2017
 *
 * The cqf_t struct is opaque — define its internals in cqf.c.
 */

#ifndef CQF_H
#define CQF_H

#include <stdint.h>
#include <stddef.h>

typedef struct cqf cqf_t;

/*
 * cqf_create — Allocate and initialize a new CQF.
 *
 * Parameters:
 *   q_bits  Number of quotient bits (>= 2). Filter has 2^q_bits slots.
 *   r_bits  Number of remainder bits (>= 1).
 *   seed    Hash seed for deterministic behavior.
 *
 * Returns pointer to new CQF, or NULL on failure.
 */
cqf_t *cqf_create(int q_bits, int r_bits, uint32_t seed);

/*
 * cqf_destroy — Free all resources. Safe to call with NULL.
 */
void cqf_destroy(cqf_t *qf);

/*
 * cqf_insert — Insert item with given count (>= 1).
 *
 * If item already exists its count is incremented by count.
 * Uses the provided hash function (cqf_hash) to map item to (q, r).
 *
 * Returns 0 on success, -1 on failure (filter full, bad args).
 */
int cqf_insert(cqf_t *qf, const char *item, int count);

/*
 * cqf_insert_raw — Insert with pre-computed quotient and remainder.
 *
 * Same semantics as cqf_insert but skips hashing.
 */
int cqf_insert_raw(cqf_t *qf, int quotient, int remainder, int count);

/*
 * cqf_query — Return the count stored for item (0 if absent).
 */
int cqf_query(const cqf_t *qf, const char *item);

/*
 * cqf_query_raw — Query with pre-computed quotient and remainder.
 */
int cqf_query_raw(const cqf_t *qf, int quotient, int remainder);

/*
 * cqf_delete — Decrement item's count by count.
 *
 * If stored count drops to zero the element is logically removed.
 * Returns 0 on success, -1 if item not found.
 */
int cqf_delete(cqf_t *qf, const char *item, int count);

/*
 * cqf_merge — Create a new CQF: multiset union of a and b.
 *
 * Counts for shared elements are SUMMED.
 * a and b must share q_bits, r_bits, and seed.
 *
 * Returns new CQF, or NULL on failure.
 */
cqf_t *cqf_merge(const cqf_t *a, const cqf_t *b);

/*
 * cqf_resize — Double slot count by stealing one remainder bit.
 *
 * After: q_bits += 1, r_bits -= 1, slot count doubles.
 * Per entry:
 *   new_q = (old_q << 1) | (old_r >> (old_r_bits - 1))
 *   new_r = old_r & ((1 << new_r_bits) - 1)
 *
 * Returns 0 on success, -1 if r_bits would become 0.
 */
int cqf_resize(cqf_t *qf);

/*
 * cqf_serialize — Write CQF state to a binary file.
 *
 * Format is implementation-defined; must round-trip with cqf_deserialize.
 * Returns 0 on success, -1 on failure.
 */
int cqf_serialize(const cqf_t *qf, const char *path);

/*
 * cqf_deserialize — Reconstruct a CQF from a file written by cqf_serialize.
 *
 * Returns new CQF, or NULL on failure.
 */
cqf_t *cqf_deserialize(const char *path);

/*
 * cqf_inner_product — Dot product of two CQFs as count vectors.
 *
 * Computes sum(count_a(x) * count_b(x)) over all x in both filters.
 * a and b must share q_bits, r_bits, and seed.
 */
int64_t cqf_inner_product(const cqf_t *a, const cqf_t *b);

/*
 * cqf_cosine_similarity — Cosine similarity between two CQF count vectors.
 *
 * inner_product(a,b) / sqrt(magnitude_sq(a) * magnitude_sq(b))
 * Returns 0.0 if either filter is empty.
 */
double cqf_cosine_similarity(const cqf_t *a, const cqf_t *b);

/*
 * Accessors
 */
int cqf_get_q_bits(const cqf_t *qf);
int cqf_get_r_bits(const cqf_t *qf);
int cqf_count_distinct(const cqf_t *qf);

/*
 * cqf_get_entries — Copy all live entries into caller-provided arrays.
 *
 * Each array must hold at least max_entries elements.
 * Returns the number of entries actually written.
 */
int cqf_get_entries(const cqf_t *qf, int *quotients, int *remainders,
                    int *counts, int max_entries);

#endif /* CQF_H */
