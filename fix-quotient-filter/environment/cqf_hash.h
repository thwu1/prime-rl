/*
 * CQF hash function — FNV-1a with splitmix64 finalizer.
 * Deterministic given the same seed and input string.
 */

#ifndef CQF_HASH_H
#define CQF_HASH_H

#include <stdint.h>

/*
 * cqf_hash — Hash a null-terminated string to (quotient, remainder).
 *
 * Uses FNV-1a 64-bit seeded with 'seed', then a splitmix64 finalizer.
 * The lower (q_bits + r_bits) bits of the hash are split:
 *   quotient  = upper q_bits
 *   remainder = lower r_bits
 */
void cqf_hash(const char *item, int q_bits, int r_bits, uint32_t seed,
              int *quotient, int *remainder);

#endif /* CQF_HASH_H */
