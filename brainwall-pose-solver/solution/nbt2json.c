/*
 * nbt2json — Convert NMMS .nbt binary trace files to JSON.
 *
 * Output: [{"cmd":"Halt"}, {"cmd":"SMove","lld":[dx,dy,dz]}, ...]
 *
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include "nmms.h"

static uint8_t *trace_data;
static int trace_pos, trace_len;

static uint8_t read_byte(void)
{
    if (trace_pos >= trace_len) {
        fprintf(stderr, "Error: trace data exhausted at position %d\n",
                trace_pos);
        exit(1);
    }
    return trace_data[trace_pos++];
}

/* Print a long linear coordinate difference as a JSON array. */
static void print_lld(int axis, int i)
{
    int val = LLD_DECODE(i);
    switch (axis) {
    case AXIS_X: printf("[%d,0,0]", val); break;
    case AXIS_Y: printf("[0,%d,0]", val); break;
    case AXIS_Z: printf("[0,0,%d]", val); break;
    default:
        fprintf(stderr, "Error: invalid lld axis %d\n", axis);
        exit(1);
    }
}

/* Print a short linear coordinate difference as a JSON array. */
static void print_sld(int axis, int i)
{
    int val = SLD_DECODE(i);
    switch (axis) {
    case AXIS_X: printf("[%d,0,0]", val); break;
    case AXIS_Y: printf("[0,%d,0]", val); break;
    case AXIS_Z: printf("[0,0,%d]", val); break;
    default:
        fprintf(stderr, "Error: invalid sld axis %d\n", axis);
        exit(1);
    }
}

int main(int argc, char *argv[])
{
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <trace.nbt>\n", argv[0]);
        return 1;
    }

    FILE *f = fopen(argv[1], "rb");
    if (!f) {
        perror("fopen");
        return 1;
    }

    fseek(f, 0, SEEK_END);
    trace_len = (int)ftell(f);
    fseek(f, 0, SEEK_SET);

    trace_data = malloc((size_t)trace_len);
    if (!trace_data) {
        fprintf(stderr, "malloc failed\n");
        fclose(f);
        return 1;
    }

    if ((int)fread(trace_data, 1, (size_t)trace_len, f) != trace_len) {
        fprintf(stderr, "Failed to read trace file\n");
        free(trace_data);
        fclose(f);
        return 1;
    }
    fclose(f);

    trace_pos = 0;
    printf("[");
    int first = 1;

    while (trace_pos < trace_len) {
        uint8_t b = read_byte();

        if (!first) printf(",");
        first = 0;

        if (b == CMD_HALT) {
            printf("{\"cmd\":\"Halt\"}");

        } else if (b == CMD_WAIT) {
            printf("{\"cmd\":\"Wait\"}");

        } else if (b == CMD_FLIP) {
            printf("{\"cmd\":\"Flip\"}");

        } else if ((b & 0x0F) == CMD_SMOVE_LOW4) {
            /* SMove lld — two bytes */
            int a = (b >> 4) & 0x03;
            uint8_t b2 = read_byte();
            int i = b2 & 0x1F;
            printf("{\"cmd\":\"SMove\",\"lld\":");
            print_lld(a, i);
            printf("}");

        } else if ((b & 0x0F) == CMD_LMOVE_LOW4) {
            /* LMove sld1 sld2 — two bytes */
            int a1 = (b >> 4) & 0x03;
            int a2 = (b >> 6) & 0x03;
            uint8_t b2 = read_byte();
            int i1 = b2 & 0x0F;
            int i2 = (b2 >> 4) & 0x0F;
            printf("{\"cmd\":\"LMove\",\"sld1\":");
            print_sld(a1, i1);
            printf(",\"sld2\":");
            print_sld(a2, i2);
            printf("}");

        } else {
            int low3 = b & CMD_LOW3_MASK;
            int nd_val = (b >> 3) & 0x1F;
            int dx = ND_DX(nd_val);
            int dy = ND_DY(nd_val);
            int dz = ND_DZ(nd_val);

            if (low3 == CMD_FUSIONP) {
                printf("{\"cmd\":\"FusionP\",\"nd\":[%d,%d,%d]}", dx, dy, dz);

            } else if (low3 == CMD_FUSIONS) {
                printf("{\"cmd\":\"FusionS\",\"nd\":[%d,%d,%d]}", dx, dy, dz);

            } else if (low3 == CMD_FISSION) {
                uint8_t m = read_byte();
                printf("{\"cmd\":\"Fission\",\"nd\":[%d,%d,%d],\"m\":%d}",
                       dx, dy, dz, m);

            } else if (low3 == CMD_FILL) {
                printf("{\"cmd\":\"Fill\",\"nd\":[%d,%d,%d]}", dx, dy, dz);

            } else {
                fprintf(stderr, "Error: unknown command byte 0x%02x "
                        "at position %d\n", b, trace_pos - 1);
                free(trace_data);
                return 1;
            }
        }
    }

    printf("]\n");
    free(trace_data);
    return 0;
}
