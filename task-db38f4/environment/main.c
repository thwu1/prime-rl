/*
 *
 * Firmware update simulator — main entry point.
 *
 * Reads an SB2-format update file, runs it through the security
 * verification pipeline, and (on success) prints the DICE UDS.
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

#include "sb2_format.h"

/* Parser interface — implementation lives in sb2_parser.o */
extern void           init_firmware(void);
extern int            parse_and_verify(const uint8_t *data, size_t len);
extern const uint8_t *get_dice_uds(void);

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <sb2_update_file>\n", argv[0]);
        return 1;
    }

    init_firmware();

    FILE *fp = fopen(argv[1], "rb");
    if (!fp) {
        perror("fopen");
        return 1;
    }

    fseek(fp, 0, SEEK_END);
    long fsz = ftell(fp);
    rewind(fp);

    if (fsz < (long)SB2_HEADER_SIZE) {
        fprintf(stderr, "ERROR: file too small for SB2 header (%ld < %d)\n",
                fsz, SB2_HEADER_SIZE);
        fclose(fp);
        return 1;
    }

    uint8_t *buf = malloc((size_t)fsz);
    if (!buf) {
        perror("malloc");
        fclose(fp);
        return 1;
    }
    if (fread(buf, 1, (size_t)fsz, fp) != (size_t)fsz) {
        fprintf(stderr, "ERROR: short read\n");
        free(buf);
        fclose(fp);
        return 1;
    }
    fclose(fp);

    printf("SB2 update: %s (%ld bytes)\n", argv[1], fsz);

    int rc = parse_and_verify(buf, (size_t)fsz);
    free(buf);

    if (rc != 0) {
        fprintf(stderr, "Update rejected (code %d)\n", rc);
        return 1;
    }

    printf("UPDATE ACCEPTED\n");

    /* Dump the DICE Unique Device Secret for diagnostics */
    const uint8_t *uds = get_dice_uds();
    printf("DICE_UDS:");
    for (int i = 0; i < 32; i++)
        printf("%02x", uds[i]);
    printf("\n");

    return 0;
}
