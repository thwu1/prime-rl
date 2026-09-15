/*
 * fastnum.h — Fast integer serialization library
 *
 * Provides optimized functions for converting between integers and
 * string representations using arithmetic techniques from performance
 * engineering research.
 *
 */

#ifndef FASTNUM_H
#define FASTNUM_H

#include <stdint.h>
#include <stddef.h>

/*
 * uint64_to_dec: Convert a uint64_t to its decimal string representation.
 *   n       — the value to convert
 *   buf     — output buffer (must be large enough for the result + '\0')
 *   bufsize — total size of buf in bytes
 *   Returns the number of characters written (excluding '\0'), or -1 on error.
 */
int uint64_to_dec(uint64_t n, char *buf, int bufsize);

/*
 * dec_to_uint64: Parse a decimal string into a uint64_t.
 *   buf    — pointer to the decimal digit characters (not necessarily null-terminated)
 *   len    — number of characters to parse
 *   result — output pointer for the parsed value
 *   Returns 0 on success, -1 on overflow, -2 on invalid input.
 *   Leading zeros (except for the string "0") are rejected as invalid.
 */
int dec_to_uint64(const char *buf, int len, uint64_t *result);

/*
 * bytes_to_hex: Encode a byte array as a lowercase hexadecimal string.
 *   Uses arithmetic nibble conversion for autovectorization potential.
 *   src    — input bytes
 *   srclen — number of input bytes
 *   dst    — output buffer (must hold at least srclen*2 + 1 bytes)
 *   dstlen — total size of dst in bytes
 *   Returns 0 on success, -1 on error.
 */
int bytes_to_hex(const uint8_t *src, size_t srclen, char *dst, size_t dstlen);

/*
 * hex_to_bytes: Decode a hexadecimal string into bytes.
 *   src    — input hex characters (must have even length)
 *   srclen — number of input characters
 *   dst    — output byte buffer (must hold at least srclen/2 bytes)
 *   dstlen — total size of dst in bytes
 *   Returns 0 on success, -1 on error (odd length, invalid character).
 */
int hex_to_bytes(const char *src, size_t srclen, uint8_t *dst, size_t dstlen);

/*
 * uint64_mul_overflow: Check whether a * b overflows uint64_t.
 *   Returns 1 if a * b > UINT64_MAX, 0 otherwise.
 */
int uint64_mul_overflow(uint64_t a, uint64_t b);

#endif /* FASTNUM_H */
