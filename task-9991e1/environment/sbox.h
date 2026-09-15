/* SIGMA-256 Block Cipher — S-box declarations */
#ifndef SBOX_H
#define SBOX_H

#include <stdint.h>

/* Four 8-bit substitution tables used in the SPN round function.
 * Each table is a permutation of {0, 1, ..., 255}.
 * Tables are applied in parallel to four bytes of the state. */
extern const uint8_t SBOX_T0[256];
extern const uint8_t SBOX_T1[256];
extern const uint8_t SBOX_T2[256];
extern const uint8_t SBOX_T3[256];

/* Query a single S-box value.
 * table_id: 0..3, input: 0..255
 * Returns S_{table_id}(input) */
uint8_t sbox_lookup(int table_id, uint8_t input);

#endif /* SBOX_H */
