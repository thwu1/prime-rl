#include "common.h"

int rle_compress(const uint8_t *in, int inlen, uint8_t *out, int outlen) {
    int oi = 0;
    int i = 0;
    while (i < inlen && oi + 2 <= outlen) {
        uint8_t current = in[i];
        int count = 1;
        while (i + count < inlen && in[i + count] == current && count < 255) {
            count++;
        }
        out[oi++] = (uint8_t)count;
        out[oi++] = current;
        i += count;
    }
    return oi;
}

int rle_decompress(const uint8_t *in, int inlen, uint8_t *out, int outlen) {
    int oi = 0;
    int i = 0;
    while (i + 1 < inlen) {
        int count = in[i];
        uint8_t val = in[i + 1];
        for (int j = 0; j < count && oi < outlen; j++) {
            out[oi++] = val;
        }
        i += 2;
    }
    return oi;
}

int delta_encode(const int32_t *in, int count, int32_t *out) {
    if (count <= 0) return 0;
    out[0] = in[0];
    for (int i = 1; i < count; i++) {
        out[i] = in[i] - in[i - 1];
    }
    return count;
}

int delta_decode(const int32_t *in, int count, int32_t *out) {
    if (count <= 0) return 0;
    out[0] = in[0];
    for (int i = 1; i < count; i++) {
        out[i] = out[i - 1] + in[i];
    }
    return count;
}

int bitpack_compress(const uint32_t *in, int count, uint8_t *out, int maxbits) {
    if (maxbits <= 0 || maxbits > 32 || count <= 0) return 0;
    uint32_t mask = (maxbits == 32) ? 0xFFFFFFFFu : ((1u << maxbits) - 1);

    int needed = (count * maxbits + 7) / 8;
    for (int i = 0; i < needed; i++) out[i] = 0;

    int byte_pos = 0;
    int bit_pos = 0;
    int total_bits = 0;

    for (int i = 0; i < count; i++) {
        uint32_t val = in[i] & mask;
        int bits_remaining = maxbits;
        while (bits_remaining > 0) {
            int bits_in_byte = 8 - bit_pos;
            if (bits_in_byte > bits_remaining) bits_in_byte = bits_remaining;
            out[byte_pos] |= (uint8_t)((val & ((1u << bits_in_byte) - 1)) << bit_pos);
            val >>= bits_in_byte;
            bits_remaining -= bits_in_byte;
            bit_pos += bits_in_byte;
            if (bit_pos >= 8) {
                byte_pos++;
                bit_pos = 0;
            }
        }
        total_bits += maxbits;
    }
    return (total_bits + 7) / 8;
}
