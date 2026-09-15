/*
 * keccak.h - Keccak-f[1600] permutation interface
 *
 * Provides the core permutation used by SHA-3 and SP 800-185 derived functions.
 */

#ifndef KECCAK_H
#define KECCAK_H

#include <stdint.h>

/*
 * Apply the Keccak-f[1600] permutation to 200 bytes of state (in-place).
 * The state is interpreted as 25 lanes of 64 bits each in little-endian byte order.
 */
void keccak_f1600(uint8_t state[200]);

#endif /* KECCAK_H */
