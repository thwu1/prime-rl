
#ifndef SMEM_BANK_H
#define SMEM_BANK_H

#include <stddef.h>

#define NUM_BANKS 32
#define BANK_WIDTH_BYTES 4

/**
 * Compute the bank index for a given byte address.
 * Banks are 4 bytes wide, mapped round-robin:
 *   bank_id = (byte_address / 4) % 32
 */
int compute_bank_id(int byte_address);

/**
 * Count bank conflicts (serialization rounds) for a warp access pattern.
 *
 * @param byte_addresses  Array of byte addresses, one per thread.
 * @param count           Number of threads (typically 32 for a warp).
 * @return  0 if empty, 1 if conflict-free, N if the most-loaded bank
 *          has N threads (requiring N serialization rounds).
 */
int count_bank_conflicts(const int *byte_addresses, size_t count);

#endif /* SMEM_BANK_H */
