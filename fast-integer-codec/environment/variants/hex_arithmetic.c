/*
 * hex_arithmetic.c — Arithmetic (Skovoroda) hex encoding
 *
 * Uses a branchless arithmetic formula to convert nibble values
 * to hex characters: val + '0' + ((val > 9) * 39).
 *
 * The key insight is that this purely arithmetic approach can be
 * autovectorized by the compiler, processing multiple bytes
 * simultaneously via SIMD instructions, unlike the table-lookup
 * approach which requires memory loads.
 *
 * Reference: Skovoroda's optimization adopted in Node.js,
 * analyzed by Daniel Lemire (2026).
 */

#include <stdint.h>
#include <stddef.h>

static inline char nibble_to_hex_arith(uint8_t val) {
    return (char)(val + '0' + ((val > 9) * ('a' - '0' - 10)));
}

int hex_encode_arithmetic(const uint8_t *src, size_t srclen, char *dst, size_t dstlen) {
    if (dstlen < srclen * 2 + 1) return -1;

    for (size_t i = 0; i < srclen; i++) {
        dst[i * 2]     = nibble_to_hex_arith(src[i] >> 4);
        dst[i * 2 + 1] = nibble_to_hex_arith(src[i] & 0x0F);
    }
    dst[srclen * 2] = '\0';

    return 0;
}
