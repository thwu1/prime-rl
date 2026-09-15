
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

static uint8_t crc8_compute(uint8_t poly_koopman, const uint8_t *data, size_t len) {
    uint8_t gen = (poly_koopman << 1) | 1;
    uint8_t crc = 0;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int j = 0; j < 8; j++) {
            if (crc & 0x80)
                crc = (crc << 1) ^ gen;
            else
                crc <<= 1;
        }
    }
    return crc;
}

static int hex_to_bytes(const char *hex, uint8_t *out, size_t *out_len) {
    size_t slen = strlen(hex);
    if (slen % 2 != 0) return -1;
    *out_len = slen / 2;
    for (size_t i = 0; i < *out_len; i++) {
        char buf[3] = {hex[2*i], hex[2*i+1], 0};
        out[i] = (uint8_t)strtoul(buf, NULL, 16);
    }
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "CRC-8 Utility\n\n");
        fprintf(stderr, "Usage:\n");
        fprintf(stderr, "  %s <poly_koopman_hex> compute <hex_data>\n", argv[0]);
        fprintf(stderr, "  %s <poly_koopman_hex> table\n", argv[0]);
        fprintf(stderr, "  %s <poly_koopman_hex> verify <hex_data> <expected_crc_hex>\n", argv[0]);
        fprintf(stderr, "\nPolynomial is in Koopman notation (e.g., 0xea or ea).\n");
        fprintf(stderr, "Data is hex-encoded bytes (e.g., 48656c6c6f for \"Hello\").\n");
        return 1;
    }

    const char *poly_str = argv[1];
    if (strncmp(poly_str, "0x", 2) == 0 || strncmp(poly_str, "0X", 2) == 0)
        poly_str += 2;
    uint8_t poly = (uint8_t)strtoul(poly_str, NULL, 16);

    const char *mode = argv[2];

    if (strcmp(mode, "compute") == 0) {
        if (argc < 4) { fprintf(stderr, "Missing data argument\n"); return 1; }
        uint8_t data[4096];
        size_t dlen;
        if (hex_to_bytes(argv[3], data, &dlen) != 0) {
            fprintf(stderr, "Invalid hex data\n");
            return 1;
        }
        uint8_t result = crc8_compute(poly, data, dlen);
        printf("0x%02x\n", result);
        return 0;
    }

    if (strcmp(mode, "table") == 0) {
        uint8_t gen = (poly << 1) | 1;
        printf("CRC-8 lookup table for Koopman=0x%02x generator=0x%02x\n", poly, gen);
        printf("---\n");
        for (int i = 0; i < 256; i++) {
            uint8_t crc = (uint8_t)i;
            for (int j = 0; j < 8; j++) {
                if (crc & 0x80)
                    crc = (crc << 1) ^ gen;
                else
                    crc <<= 1;
            }
            printf("0x%02x: 0x%02x\n", i, crc);
        }
        return 0;
    }

    if (strcmp(mode, "verify") == 0) {
        if (argc < 5) { fprintf(stderr, "Missing arguments\n"); return 1; }
        uint8_t data[4096];
        size_t dlen;
        if (hex_to_bytes(argv[3], data, &dlen) != 0) {
            fprintf(stderr, "Invalid hex data\n");
            return 1;
        }
        uint8_t expected = (uint8_t)strtoul(argv[4], NULL, 16);
        uint8_t got = crc8_compute(poly, data, dlen);
        if (got == expected) {
            printf("PASS (0x%02x)\n", got);
            return 0;
        } else {
            printf("FAIL: expected 0x%02x, got 0x%02x\n", expected, got);
            return 1;
        }
    }

    fprintf(stderr, "Unknown mode: %s\n", mode);
    return 1;
}
