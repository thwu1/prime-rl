/*
 * P-256 Montgomery-domain field arithmetic library interface.
 *
 * All field elements are represented as arrays of 4 uint64_t in
 * little-endian limb order (limb[0] is least significant).
 *
 * Montgomery domain: an element a is stored as aR mod p, where R = 2^256.
 * All inputs and outputs are fully reduced (< p_256).
 * Output buffers may alias input buffers.
 */

#ifndef P256_MONT_H
#define P256_MONT_H

#include <stdint.h>

/*
 * Montgomery multiplication: z = (x * y * R^{-1}) mod p_256
 * where R = 2^256.
 */
void p256_montmul(uint64_t z[4], const uint64_t x[4], const uint64_t y[4]);

/*
 * Montgomery squaring: z = (x^2 * R^{-1}) mod p_256
 */
void p256_montsqr(uint64_t z[4], const uint64_t x[4]);

/*
 * Modular addition: z = (x + y) mod p_256
 */
void p256_montadd(uint64_t z[4], const uint64_t x[4], const uint64_t y[4]);

/*
 * Modular subtraction: z = (x - y) mod p_256
 */
void p256_montsub(uint64_t z[4], const uint64_t x[4], const uint64_t y[4]);

/*
 * Convert to Montgomery domain: z = (x * R) mod p_256
 */
void p256_tomont(uint64_t z[4], const uint64_t x[4]);

/*
 * Convert from Montgomery domain: z = (x * R^{-1}) mod p_256
 */
void p256_frommont(uint64_t z[4], const uint64_t x[4]);

/*
 * Modular multiplicative inverse in Montgomery domain:
 * Given x (in Montgomery form), compute z such that
 * montmul(z, x) = R mod p_256 (i.e., the Montgomery representation of 1).
 *
 * Undefined when x = 0.
 */
void p256_inv(uint64_t z[4], const uint64_t x[4]);

#endif /* P256_MONT_H */
