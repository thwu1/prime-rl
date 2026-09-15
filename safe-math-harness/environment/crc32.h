/*
 * crc32.h - CRC32 checksum infrastructure for differential testing
 *
 * Provides transparent_crc() for hashing program state into a
 * CRC32 checksum, used to detect divergent behavior across
 * compiler optimization levels.
 *
 */

#ifndef CRC32_H
#define CRC32_H

#include <stdint.h>
#include <stdio.h>

static uint32_t crc32_tab[256];
static uint32_t crc32_context = 0xFFFFFFFFUL;

static void crc32_init(void) {
    uint32_t crc;
    const uint32_t poly = 0xEDB88320UL;
    int i, j;
    for (i = 0; i < 256; i++) {
        crc = (uint32_t)i;
        for (j = 0; j < 8; j++) {
            if (crc & 1) {
                crc = (crc >> 1) ^ poly;
            } else {
                crc >>= 1;
            }
        }
        crc32_tab[i] = crc;
    }
}

static void crc32_byte(uint8_t b) {
    crc32_context = ((crc32_context >> 8) & 0x00FFFFFFUL) ^
                    crc32_tab[(crc32_context ^ b) & 0xFF];
}

static void crc32_8bytes(uint64_t val) {
    crc32_byte((val >>  0) & 0xff);
    crc32_byte((val >>  8) & 0xff);
    crc32_byte((val >> 16) & 0xff);
    crc32_byte((val >> 24) & 0xff);
    crc32_byte((val >> 32) & 0xff);
    crc32_byte((val >> 40) & 0xff);
    crc32_byte((val >> 48) & 0xff);
    crc32_byte((val >> 56) & 0xff);
}

static void transparent_crc(uint64_t val, const char *vname, int flag) {
    crc32_8bytes(val);
    if (flag) {
        printf("...checksum after hashing %s : %lx\n", vname,
               (unsigned long)(crc32_context ^ 0xFFFFFFFFUL));
    }
}

static uint32_t crc32_finalize(void) {
    return crc32_context ^ 0xFFFFFFFFUL;
}

#endif /* CRC32_H */
