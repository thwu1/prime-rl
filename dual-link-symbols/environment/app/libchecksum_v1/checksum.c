#include "checksum.h"

/*
 * Adler-32 checksum.
 */
uint32_t checksum_adler32(const uint8_t *data, size_t len) {
    uint32_t a = 1, b = 0;
    for (size_t i = 0; i < len; i++) {
        a = (a + data[i]) % 65521;
        b = b + a;
    }
    return (b << 16) | a;
}

/*
 * CRC-32 (ISO 3309 / ITU-T V.42).
 */
static uint32_t crc32_for_byte(uint32_t byte) {
    for (int i = 0; i < 8; i++) {
        if (byte & 1)
            byte = (byte >> 1) ^ 0xEDB88320;
        else
            byte >>= 1;
    }
    return byte;
}

uint32_t checksum_crc32(const uint8_t *data, size_t len) {
    uint32_t crc = 0xFFFFFFFF;
    for (size_t i = 0; i < len; i++)
        crc = (crc >> 8) ^ crc32_for_byte((crc ^ data[i]) & 0xFF);
    return crc ^ 0xFFFFFFFF;
}

/*
 * DJB2 hash (Dan Bernstein).
 */
uint32_t checksum_djb2(const uint8_t *data, size_t len) {
    uint32_t hash = 5381;
    for (size_t i = 0; i < len; i++)
        hash = ((hash << 5) + hash) + data[i];
    return hash;
}

/*
 * Fletcher-16 checksum.
 */
uint32_t checksum_fletcher16(const uint8_t *data, size_t len) {
    uint16_t sum1 = 0, sum2 = 0;
    for (size_t i = 0; i < len; i++) {
        sum1 = (sum1 + data[i]) % 256;
        sum2 = (sum2 + sum1) % 256;
    }
    return ((uint32_t)sum2 << 8) | sum1;
}

/*
 * FNV-1a 32-bit hash.
 */
uint32_t checksum_fnv1a(const uint8_t *data, size_t len) {
    uint32_t hash = 0x811C9DC5;
    for (size_t i = 0; i < len; i++) {
        hash ^= data[i];
        hash *= 0x01000193;
    }
    return hash;
}

/*
 * Rotate-XOR hash.
 */
uint32_t checksum_rotxor(const uint8_t *data, size_t len) {
    uint32_t hash = 0;
    for (size_t i = 0; i < len; i++)
        hash = ((hash >> 5) | (hash << 27)) ^ data[i];
    return hash;
}

/*
 * SDBM hash.
 */
uint32_t checksum_sdbm(const uint8_t *data, size_t len) {
    uint32_t hash = 0;
    for (size_t i = 0; i < len; i++)
        hash = data[i] + (hash << 6) + (hash << 16) - hash;
    return hash;
}

/*
 * XOR-8 fold hash.
 */
uint32_t checksum_xor8(const uint8_t *data, size_t len) {
    uint8_t hash = 0;
    for (size_t i = 0; i < len; i++)
        hash ^= data[i];
    return (uint32_t)hash;
}
