/*
 * hex_table.c — Table-lookup hex encoding
 *
 * Classic approach: uses a 16-byte character lookup table to map
 * each nibble value (0-15) to its corresponding hex character.
 * Simple and correct, but the table load prevents autovectorization
 * by the compiler, limiting throughput.
 */

#include <stdint.h>
#include <stddef.h>

static const char hex_lut[16] = {
    '0', '1', '2', '3', '4', '5', '6', '7',
    '8', '9', 'a', 'b', 'c', 'd', 'e', 'f'
};

int hex_encode_table(const uint8_t *src, size_t srclen, char *dst, size_t dstlen) {
    if (dstlen < srclen * 2 + 1) return -1;

    for (size_t i = 0; i < srclen; i++) {
        dst[i * 2]     = hex_lut[src[i] >> 4];
        dst[i * 2 + 1] = hex_lut[src[i] & 0x0F];
    }
    dst[srclen * 2] = '\0';

    return 0;
}
