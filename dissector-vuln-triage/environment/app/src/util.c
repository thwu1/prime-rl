#include "ndp.h"

/*
 * Standard CRC32 implementation (ITU-T V.42 / ISO 3309).
 * Same polynomial and algorithm as zlib, gzip, and Python's binascii.crc32.
 * Polynomial: 0xEDB88320 (bit-reversed representation of 0x04C11DB7).
 */

static uint32_t crc32_table[256];
static int table_initialized = 0;

static void init_crc32_table(void) {
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t crc = i;
        for (int j = 0; j < 8; j++) {
            if (crc & 1)
                crc = (crc >> 1) ^ 0xEDB88320U;
            else
                crc >>= 1;
        }
        crc32_table[i] = crc;
    }
    table_initialized = 1;
}

uint32_t ndp_crc32(const uint8_t *data, size_t len) {
    if (!table_initialized)
        init_crc32_table();

    uint32_t crc = 0xFFFFFFFFU;
    for (size_t i = 0; i < len; i++) {
        crc = crc32_table[(crc ^ data[i]) & 0xFF] ^ (crc >> 8);
    }
    return crc ^ 0xFFFFFFFFU;
}
