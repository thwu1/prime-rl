/*
 * fastnum.h — Fast integer serialization library
 */

#ifndef FASTNUM_H
#define FASTNUM_H

#include <stdint.h>
#include <stddef.h>

int uint64_to_dec(uint64_t n, char *buf, int bufsize);
int dec_to_uint64(const char *buf, int len, uint64_t *result);
int bytes_to_hex(const uint8_t *src, size_t srclen, char *dst, size_t dstlen);
int hex_to_bytes(const char *src, size_t srclen, uint8_t *dst, size_t dstlen);
int uint64_mul_overflow(uint64_t a, uint64_t b);

#endif /* FASTNUM_H */
