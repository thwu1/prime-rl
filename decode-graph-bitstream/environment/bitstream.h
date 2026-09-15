/*
 * bitstream.h — Shared WGEF bitstream reader library
 *
 * Big-endian (MSB-first) bit stream reader with decoders for
 * unary, Elias gamma, minimal binary, and Boldi-Vigna zeta_k codes.
 */

#ifndef WGEF_BITSTREAM_H
#define WGEF_BITSTREAM_H

#include <stdint.h>
#include <stddef.h>

typedef struct {
    const uint8_t *data;
    size_t len;
    size_t byte_pos;
    int bit_pos;
    size_t total_bits_read;
} WgefBitReader;

void wgef_br_init(WgefBitReader *r, const uint8_t *data, size_t len);
void wgef_br_seek(WgefBitReader *r, size_t bit_offset);
int wgef_br_read_bit(WgefBitReader *r);
uint64_t wgef_br_read_bits(WgefBitReader *r, int n);
uint64_t wgef_br_read_unary(WgefBitReader *r);
uint64_t wgef_br_read_gamma(WgefBitReader *r);
uint64_t wgef_br_read_minimal_binary(WgefBitReader *r, uint64_t bound);
uint64_t wgef_br_read_zeta(WgefBitReader *r, int k);

/*
 * Load a WGEF file: verify magic, return full file data (caller frees).
 * Sets *fsize_out to total file size. Returns NULL on error.
 * Payload starts at returned_ptr + 4 (after WGEF magic).
 */
uint8_t *wgef_load(const char *path, size_t *fsize_out);

#endif /* WGEF_BITSTREAM_H */
