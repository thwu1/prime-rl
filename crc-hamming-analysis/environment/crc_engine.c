/*
 * crc_engine.c — CRC-8 computation engine (table-driven)
 *
 * Usage: ./crc_engine <poly_hex> <input_file>
 *   poly_hex:    standard-form 9-bit polynomial in hex (e.g., 0x1cf)
 *   input_file:  path to binary file whose entire contents are the message
 *
 * CRC-8: MSB-first, init=0, no reflection, no final XOR.
 * Outputs: decimal CRC value followed by newline.
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

static uint8_t crc_table[256];

static void build_table(uint8_t poly) {
    for (int i = 0; i < 256; i++) {
        uint8_t crc = (uint8_t)i;
        for (int j = 0; j < 8; j++) {
            if (crc & 0x80)
                crc = (crc << 1) ^ poly;
            else
                crc <<= 1;
        }
        crc_table[i] = crc;
    }
}

static uint8_t compute_crc(const uint8_t *data, size_t len) {
    uint8_t crc = 0;
    for (size_t i = 0; i < len; i++)
        crc = crc_table[crc ^ data[i]];
    return crc;
}

int main(int argc, char *argv[]) {
    if (argc != 3) {
        fprintf(stderr, "Usage: %s <poly_hex> <input_file>\n", argv[0]);
        return 1;
    }

    unsigned long poly_full = strtoul(argv[1], NULL, 16);
    uint8_t poly = (uint8_t)(poly_full & 0xFF);

    FILE *f = fopen(argv[2], "rb");
    if (!f) {
        perror(argv[2]);
        return 1;
    }

    fseek(f, 0, SEEK_END);
    long fsize = ftell(f);
    rewind(f);

    uint8_t *buf = malloc(fsize);
    if (!buf) {
        fprintf(stderr, "malloc failed\n");
        fclose(f);
        return 1;
    }

    if ((long)fread(buf, 1, fsize, f) != fsize) {
        fprintf(stderr, "read error\n");
        free(buf);
        fclose(f);
        return 1;
    }
    fclose(f);

    build_table(poly);
    printf("%u\n", compute_crc(buf, (size_t)fsize));

    free(buf);
    return 0;
}
