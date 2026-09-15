#include <stdint.h>

/*
 * Nibble packing library for NF4 quantized indices.
 *
 * Convention: each byte stores two 4-bit indices.
 *   - First index in low nibble (bits 0-3)
 *   - Second index in high nibble (bits 4-7)
 */

void bnb_pack_nibbles(const uint8_t *indices, uint8_t *out, int count) {
    int nbytes = (count + 1) / 2;
    for (int i = 0; i < nbytes; i++) {
        uint8_t lo = indices[2 * i] & 0xF;
        uint8_t hi = (2 * i + 1 < count) ? (indices[2 * i + 1] & 0xF) : 0;
        out[i] = lo | (hi << 4);
    }
}

void bnb_unpack_nibbles(const uint8_t *packed, uint8_t *out, int count) {
    int byte_idx = 0;
    for (int i = 0; i < count; i += 2) {
        out[i] = packed[byte_idx] & 0xF;
        if (i + 1 < count) {
            out[i + 1] = (packed[byte_idx] >> 4) & 0xF;
        }
        byte_idx++;
    }
}

int bnb_packed_size(int count) {
    return (count + 1) / 2;
}
