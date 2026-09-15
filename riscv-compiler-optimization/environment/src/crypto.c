#include "common.h"

uint32_t crc32_compute(const uint8_t *data, size_t len) {
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int j = 0; j < 8; j++) {
            if (crc & 1u)
                crc = (crc >> 1) ^ 0xEDB88320u;
            else
                crc >>= 1;
        }
    }
    return ~crc;
}

void simple_hash(const uint8_t *data, size_t len, uint8_t *out) {
    uint32_t h[4] = {0x6a09e667u, 0xbb67ae85u, 0x3c6ef372u, 0xa54ff53au};

    for (size_t i = 0; i < len; i++) {
        uint32_t t = h[0] + data[i];
        t = (t << 5) | (t >> 27);
        t ^= h[1];
        h[0] = h[1];
        h[1] = h[2];
        h[2] = h[3];
        h[3] = t;
    }

    for (int r = 0; r < 16; r++) {
        uint32_t t = h[0] ^ ((h[1] << 13) | (h[1] >> 19));
        t += h[2];
        h[0] = h[1];
        h[1] = h[2];
        h[2] = h[3];
        h[3] = t;
    }

    for (int i = 0; i < 4; i++) {
        out[i * 4 + 0] = (uint8_t)(h[i] >> 24);
        out[i * 4 + 1] = (uint8_t)(h[i] >> 16);
        out[i * 4 + 2] = (uint8_t)(h[i] >> 8);
        out[i * 4 + 3] = (uint8_t)(h[i]);
    }
}

/*
 * XTEA block cipher with 32 rounds (hardcoded).
 * The fixed round count allows -O3 to unroll the loop, producing
 * significantly larger code than -Os which keeps it as a compact loop.
 */
#define XTEA_ROUNDS 32

void xtea_encrypt(uint32_t v[2], const uint32_t key[4]) {
    uint32_t v0 = v[0], v1 = v[1], sum = 0;
    const uint32_t delta = 0x9E3779B9u;
    for (int i = 0; i < XTEA_ROUNDS; i++) {
        v0 += (((v1 << 4) ^ (v1 >> 5)) + v1) ^ (sum + key[sum & 3]);
        sum += delta;
        v1 += (((v0 << 4) ^ (v0 >> 5)) + v0) ^ (sum + key[(sum >> 11) & 3]);
    }
    v[0] = v0;
    v[1] = v1;
}

void xtea_decrypt(uint32_t v[2], const uint32_t key[4]) {
    uint32_t v0 = v[0], v1 = v[1];
    const uint32_t delta = 0x9E3779B9u;
    uint32_t sum = delta * XTEA_ROUNDS;
    for (int i = 0; i < XTEA_ROUNDS; i++) {
        v1 -= (((v0 << 4) ^ (v0 >> 5)) + v0) ^ (sum + key[(sum >> 11) & 3]);
        sum -= delta;
        v0 -= (((v1 << 4) ^ (v1 >> 5)) + v1) ^ (sum + key[sum & 3]);
    }
    v[0] = v0;
    v[1] = v1;
}
