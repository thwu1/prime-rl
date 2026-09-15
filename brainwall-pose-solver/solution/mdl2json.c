/*
 * mdl2json — Convert NMMS .mdl binary model files to JSON.
 *
 * Output: {"resolution":R,"filled":[[x,y,z],...]}
 *
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include "nmms.h"

int main(int argc, char *argv[])
{
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <model.mdl>\n", argv[0]);
        return 1;
    }

    FILE *f = fopen(argv[1], "rb");
    if (!f) {
        perror("fopen");
        return 1;
    }

    uint8_t R;
    if (fread(&R, 1, 1, f) != 1) {
        fprintf(stderr, "Failed to read resolution byte\n");
        fclose(f);
        return 1;
    }

    int total_bits = (int)R * R * R;
    int nbytes = (total_bits + 7) / 8;
    uint8_t *bits = calloc((size_t)nbytes, 1);
    if (!bits) {
        fprintf(stderr, "calloc failed\n");
        fclose(f);
        return 1;
    }

    size_t read_count = fread(bits, 1, (size_t)nbytes, f);
    fclose(f);

    if ((int)read_count < nbytes) {
        fprintf(stderr, "Warning: read %zu of %d expected bytes\n",
                read_count, nbytes);
    }

    printf("{\"resolution\":%d,\"filled\":[", R);

    int first = 1;
    for (int x = 0; x < R; x++) {
        for (int y = 0; y < R; y++) {
            for (int z = 0; z < R; z++) {
                int idx = x * R * R + y * R + z;
                if (bits[idx / 8] & (1 << (idx % 8))) {
                    if (!first) printf(",");
                    printf("[%d,%d,%d]", x, y, z);
                    first = 0;
                }
            }
        }
    }

    printf("]}\n");
    free(bits);
    return 0;
}
