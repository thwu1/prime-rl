/*
 * msgcheck - Mode S message integrity validator
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#define MAX_MSGS 512
#define MSG_BYTES 14

static unsigned int crc24(const unsigned char *msg, int nbytes) {
    unsigned int crc = 0;
    for (int i = 0; i < nbytes; i++) {
        crc ^= ((unsigned int)msg[i]) << 16;
        for (int j = 0; j < 8; j++) {
            if (crc & 0x800000)
                crc = (crc << 1) ^ 0x1FFF409;
            else
                crc <<= 1;
        }
    }
    return crc & 0xFFFFFF;
}

static int try_correct(unsigned char *msg, int nbytes) {
    if (crc24(msg, nbytes) == 0) return 0;
    unsigned char trial[MSG_BYTES];
    for (int bit = 0; bit < nbytes * 8; bit++) {
        memcpy(trial, msg, nbytes);
        trial[bit / 8] ^= (1 << (7 - (bit % 8)));
        if (crc24(trial, nbytes) == 0) {
            memcpy(msg, trial, nbytes);
            return 1;
        }
    }
    return -1;
}

static int hex_to_bytes(const char *hex, unsigned char *out, int max) {
    int len = strlen(hex);
    if (len % 2 || len / 2 > max) return -1;
    for (int i = 0; i < len / 2; i++) {
        unsigned int v;
        if (sscanf(hex + 2 * i, "%2x", &v) != 1) return -1;
        out[i] = (unsigned char)v;
    }
    return len / 2;
}

typedef struct {
    char hex[30];
    int status;
    int df;
    int tc;
} MsgResult;

int main(int argc, char **argv) {
    int verbose = 0, json = 0;
    const char *fname = NULL;

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-v") || !strcmp(argv[i], "--verbose"))
            verbose = 1;
        else if (!strcmp(argv[i], "-j") || !strcmp(argv[i], "--json"))
            json = 1;
        else if (!strcmp(argv[i], "-h") || !strcmp(argv[i], "--help")) {
            printf("Usage: %s [OPTIONS] <messages_file>\n", argv[0]);
            printf("Validate Mode S message integrity.\n\n");
            printf("Options:\n");
            printf("  -v, --verbose  Per-message details\n");
            printf("  -j, --json     JSON output\n");
            printf("  -h, --help     This help\n");
            return 0;
        } else
            fname = argv[i];
    }

    if (!fname) {
        fprintf(stderr, "Usage: %s [OPTIONS] <messages_file>\n", argv[0]);
        return 1;
    }

    FILE *f = fopen(fname, "r");
    if (!f) { fprintf(stderr, "Cannot open %s\n", fname); return 1; }

    MsgResult results[MAX_MSGS];
    int total = 0, valid = 0, corrected = 0, invalid = 0, df17 = 0;
    char line[512];

    while (fgets(line, sizeof(line), f) && total < MAX_MSGS) {
        char *p = line;
        while (*p && isspace((unsigned char)*p)) p++;
        int len = strlen(p);
        while (len > 0 && isspace((unsigned char)p[len - 1])) p[--len] = '\0';
        if (!len || p[0] != '*' || p[len - 1] != ';') continue;

        int hlen = len - 2;
        if (hlen != 28) continue;
        char hex[30];
        memcpy(hex, p + 1, 28);
        hex[28] = '\0';
        for (int k = 0; k < 28; k++) hex[k] = toupper((unsigned char)hex[k]);

        unsigned char msg[MSG_BYTES];
        if (hex_to_bytes(hex, msg, MSG_BYTES) != MSG_BYTES) continue;

        int st = try_correct(msg, MSG_BYTES);
        if (st == 0) valid++;
        else if (st == 1) corrected++;
        else { invalid++; st = -1; }

        int d = (msg[0] >> 3) & 0x1F;
        int t = (d == 17) ? ((msg[4] >> 3) & 0x1F) : 0;
        if (d == 17) df17++;

        strcpy(results[total].hex, hex);
        results[total].status = st;
        results[total].df = d;
        results[total].tc = t;
        total++;
    }
    fclose(f);

    if (json) {
        printf("{\n");
        printf("  \"total_messages\": %d,\n", total);
        printf("  \"crc_valid\": %d,\n", valid);
        printf("  \"crc_corrected\": %d,\n", corrected);
        printf("  \"crc_invalid\": %d,\n", invalid);
        printf("  \"df17_messages\": %d", df17);
        if (verbose) {
            printf(",\n  \"messages\": [\n");
            for (int i = 0; i < total; i++) {
                const char *s = results[i].status == 0 ? "valid" :
                               results[i].status == 1 ? "corrected" : "invalid";
                printf("    {\"hex\": \"%s\", \"crc_status\": \"%s\", \"df\": %d, \"tc\": %d}",
                    results[i].hex, s, results[i].df, results[i].tc);
                printf("%s\n", i < total - 1 ? "," : "");
            }
            printf("  ]\n");
        } else {
            printf("\n");
        }
        printf("}\n");
    } else {
        printf("Mode S Message Integrity Report\n");
        printf("================================\n");
        printf("Total:     %d\n", total);
        printf("CRC OK:    %d\n", valid);
        printf("Corrected: %d\n", corrected);
        printf("Invalid:   %d\n", invalid);
        printf("DF17:      %d\n", df17);
        if (verbose) {
            printf("\nDetails:\n");
            for (int i = 0; i < total; i++) {
                const char *s = results[i].status == 0 ? "OK" :
                               results[i].status == 1 ? "CORRECTED" : "INVALID";
                printf("  [%2d] %s DF=%d TC=%d %s\n",
                    i + 1, results[i].hex, results[i].df, results[i].tc, s);
            }
        }
    }

    return invalid > 0 ? 1 : 0;
}
