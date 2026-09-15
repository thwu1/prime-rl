/* record_processor.c — reference implementation */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#define MAX_RECORDS 1024
#define MAX_CATS 64
#define POLY_MOD 998244353ULL

typedef struct {
    char id[20];
    int32_t category;
    int64_t amount;
    uint32_t flags;
    int16_t weight;
    uint64_t fingerprint;
} Record;

typedef struct {
    int32_t category;
    int64_t total_weighted;
    int64_t min_amount;
    int64_t max_amount;
    uint32_t or_flags;
    uint32_t xor_flags;
    int32_t count;
    uint32_t hash;
    uint64_t fp_xor;
} CatStats;

uint32_t rolling_hash(const uint8_t *data, size_t len, uint32_t seed) {
    uint32_t h = seed;
    for (size_t i = 0; i < len; i++) {
        h = h * 31 + data[i];
        h ^= (h >> 16);
    }
    return h;
}

int encode_varint(uint64_t val, uint8_t *buf) {
    int n = 0;
    do {
        buf[n] = (uint8_t)(val & 0x7F);
        val >>= 7;
        if (val > 0) buf[n] |= 0x80;
        n++;
    } while (val > 0);
    return n;
}

int decode_varint(const uint8_t *buf, size_t len, uint64_t *out) {
    uint64_t result = 0;
    unsigned shift = 0;
    for (size_t i = 0; i < len && i < 10; i++) {
        result |= (uint64_t)(buf[i] & 0x7F) << shift;
        shift += 7;
        if (!(buf[i] & 0x80)) {
            *out = result;
            return (int)(i + 1);
        }
    }
    return -1;
}

uint16_t read_be16(const uint8_t *buf) {
    return ((uint16_t)buf[0] << 8) | (uint16_t)buf[1];
}

uint64_t zigzag_encode(int64_t n) {
    return (uint64_t)((n << 1) ^ (n >> 63));
}

int64_t zigzag_decode(uint64_t n) {
    return (int64_t)((n >> 1) ^ -(int64_t)(n & 1));
}

uint64_t compute_fingerprint(const uint8_t *data, size_t len) {
    uint64_t h = 1;
    for (size_t i = 0; i < len; i++) {
        h = (h * 257 + data[i]) % POLY_MOD;
    }
    return h;
}

int parse_record(const char *line, Record *rec) {
    const char *p = line;
    const char *delim;
    int flen;

    delim = strchr(p, '|');
    if (!delim) return -1;
    flen = (int)(delim - p);
    if (flen > 19) flen = 19;
    memcpy(rec->id, p, flen);
    rec->id[flen] = '\0';
    p = delim + 1;

    delim = strchr(p, '|');
    if (!delim) return -1;
    rec->category = (int32_t)strtol(p, NULL, 10);
    p = delim + 1;

    delim = strchr(p, '|');
    if (!delim) return -1;
    rec->amount = strtoll(p, NULL, 10);
    p = delim + 1;

    delim = strchr(p, '|');
    if (!delim) return -1;
    rec->flags = (uint32_t)strtoul(p, NULL, 16);
    p = delim + 1;

    rec->weight = (int16_t)strtol(p, NULL, 10);

    uint8_t fp_data[28];
    size_t id_len = strlen(rec->id);
    memcpy(fp_data, rec->id, id_len);
    for (int b = 0; b < 8; b++)
        fp_data[id_len + b] = (uint8_t)((rec->amount >> (b * 8)) & 0xFF);
    rec->fingerprint = compute_fingerprint(fp_data, id_len + 8);

    return 0;
}

int aggregate(Record *recs, int nrecs, CatStats *stats) {
    int ncats = 0;
    for (int i = 0; i < nrecs; i++) {
        int found = -1;
        for (int j = 0; j < ncats; j++) {
            if (stats[j].category == recs[i].category) {
                found = j;
                break;
            }
        }
        if (found < 0) {
            if (ncats >= MAX_CATS) continue;
            found = ncats++;
            stats[found].category = recs[i].category;
            stats[found].total_weighted = 0;
            stats[found].min_amount = recs[i].amount;
            stats[found].max_amount = recs[i].amount;
            stats[found].or_flags = 0;
            stats[found].xor_flags = 0;
            stats[found].count = 0;
            stats[found].hash = 0;
            stats[found].fp_xor = 0;
        }
        stats[found].total_weighted += recs[i].amount * (int64_t)recs[i].weight;
        if (recs[i].amount < stats[found].min_amount)
            stats[found].min_amount = recs[i].amount;
        if (recs[i].amount > stats[found].max_amount)
            stats[found].max_amount = recs[i].amount;
        stats[found].or_flags |= recs[i].flags;
        stats[found].xor_flags ^= recs[i].flags;
        stats[found].count++;
        stats[found].hash = rolling_hash(
            (const uint8_t *)recs[i].id, strlen(recs[i].id),
            stats[found].hash);
        uint8_t amt_bytes[8];
        for (int b = 0; b < 8; b++)
            amt_bytes[b] = (uint8_t)((recs[i].amount >> (b * 8)) & 0xFF);
        stats[found].hash = rolling_hash(amt_bytes, 8, stats[found].hash);
        stats[found].fp_xor ^= recs[i].fingerprint;
    }
    return ncats;
}

int compare_stats(const void *a, const void *b) {
    const CatStats *sa = (const CatStats *)a;
    const CatStats *sb = (const CatStats *)b;
    int64_t avg_a = sa->count > 0 ? sa->total_weighted / sa->count : 0;
    int64_t avg_b = sb->count > 0 ? sb->total_weighted / sb->count : 0;
    if (avg_a > avg_b) return -1;
    if (avg_a < avg_b) return 1;
    return sa->category - sb->category;
}

int main(int argc, char **argv) {
    FILE *fp = stdin;
    if (argc > 1) {
        fp = fopen(argv[1], "r");
        if (!fp) { perror(argv[1]); return 1; }
    }
    Record records[MAX_RECORDS];
    int nrecs = 0;
    char line[512];
    while (fgets(line, sizeof(line), fp) && nrecs < MAX_RECORDS) {
        if (line[0] == '#' || line[0] == '\n' || line[0] == '\r') continue;
        line[strcspn(line, "\r\n")] = '\0';
        if (parse_record(line, &records[nrecs]) == 0) nrecs++;
    }
    if (fp != stdin) fclose(fp);

    CatStats stats[MAX_CATS];
    int ncats = aggregate(records, nrecs, stats);
    qsort(stats, ncats, sizeof(CatStats), compare_stats);

    printf("=== RECORD ANALYSIS REPORT ===\n");
    printf("TOTAL_RECORDS: %d\n", nrecs);
    printf("CATEGORIES: %d\n", ncats);
    printf("---\n");

    uint32_t global_hash = 0;
    for (int i = 0; i < ncats; i++) {
        int64_t avg = stats[i].count > 0 ?
            stats[i].total_weighted / stats[i].count : 0;
        printf("CAT[%03d]: WAVG=%lld MIN=%lld MAX=%lld "
               "OR_FL=0x%08X XOR_FL=0x%08X CNT=%d HASH=0x%08X FP=0x%016llX\n",
               stats[i].category, (long long)avg,
               (long long)stats[i].min_amount,
               (long long)stats[i].max_amount,
               stats[i].or_flags, stats[i].xor_flags,
               stats[i].count, stats[i].hash,
               (unsigned long long)stats[i].fp_xor);
        uint8_t vbuf[10];
        uint64_t abs_avg = avg >= 0 ? (uint64_t)avg : (uint64_t)(-avg);
        int vlen = encode_varint(abs_avg, vbuf);
        global_hash = rolling_hash(vbuf, vlen, global_hash);
    }

    printf("---\n");
    printf("GLOBAL_HASH: 0x%08X\n", global_hash);

    printf("---\nCOMPACT_SERIAL:\n");
    int64_t prev_wavg = 0;
    for (int i = 0; i < ncats; i++) {
        int64_t avg = stats[i].count > 0 ?
            stats[i].total_weighted / stats[i].count : 0;
        int64_t delta = avg - prev_wavg;
        prev_wavg = avg;
        uint64_t zz = zigzag_encode(delta);
        uint8_t vbuf[10];
        int vlen = encode_varint(zz, vbuf);
        printf("  S[%03d]: D=%lld ZZ=%llu VL=%d HEX=",
               stats[i].category, (long long)delta,
               (unsigned long long)zz, vlen);
        for (int j = 0; j < vlen; j++) printf("%02X", vbuf[j]);
        printf("\n");
        uint64_t dec_zz = 0;
        decode_varint(vbuf, vlen, &dec_zz);
        int64_t dec_delta = zigzag_decode(dec_zz);
        if (dec_delta != delta) {
            printf("  ROUNDTRIP_FAIL: expected %lld got %lld\n",
                   (long long)delta, (long long)dec_delta);
        }
    }

    printf("---\nVARINT_CHECK:\n");
    uint64_t test_vals[] = {0, 1, 127, 128, 255, 256, 16383, 16384,
                            0x7FFFFFFFU, 0x80000000ULL, 0xFFFFFFFFULL,
                            0x100000000ULL, 0xFFFFFFFFFFFFFFFFULL};
    int ntests = (int)(sizeof(test_vals) / sizeof(test_vals[0]));
    for (int i = 0; i < ntests; i++) {
        uint8_t buf[10];
        int nbytes = encode_varint(test_vals[i], buf);
        uint64_t decoded = 0;
        int consumed = decode_varint(buf, nbytes, &decoded);
        printf("  V(%llu): ENC=%d DEC=%d %s\n",
               (unsigned long long)test_vals[i], nbytes, consumed,
               (decoded == test_vals[i] && consumed == nbytes) ? "OK" : "FAIL");
    }

    printf("---\nBE16_CHECK:\n");
    uint8_t be_tests[][2] = {{0x00, 0x01}, {0x01, 0x00}, {0xFF, 0xFE},
                              {0x80, 0x00}, {0x7F, 0xFF}, {0x00, 0x00}};
    for (int i = 0; i < 6; i++) {
        printf("  [%02X,%02X] -> %u\n", be_tests[i][0], be_tests[i][1],
               read_be16(be_tests[i]));
    }

    printf("---\nZIGZAG_CHECK:\n");
    int64_t zz_tests[] = {0, 1, -1, 2, -2, 127, -128, 2147483647LL,
                           -2147483648LL, 100000000000LL, -999999999999LL};
    int nzz = (int)(sizeof(zz_tests) / sizeof(zz_tests[0]));
    for (int i = 0; i < nzz; i++) {
        uint64_t enc = zigzag_encode(zz_tests[i]);
        int64_t dec = zigzag_decode(enc);
        printf("  ZZ(%lld): ENC=%llu DEC=%lld %s\n",
               (long long)zz_tests[i], (unsigned long long)enc,
               (long long)dec,
               (dec == zz_tests[i]) ? "OK" : "FAIL");
    }

    return 0;
}
