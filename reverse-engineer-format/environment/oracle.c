/*
 * RPACK v1 binary serialization format encoder/decoder.
 *
 * Format specification (NOT visible to the agent):
 *
 * Header:  0xCF 0xB0 0x01
 *
 * Type tags:
 *   0x00        null
 *   0x01        false
 *   0x02        true
 *   0x10..0x1F  fixint 0-15  (value = tag - 0x10, no extra bytes)
 *   0x20        int8   (1 byte, signed)
 *   0x21        int16  (2 bytes, little-endian, signed)
 *   0x22        int32  (4 bytes, little-endian, signed)
 *   0x23        int64  (8 bytes, little-endian, signed)
 *   0x30        float64 (8 bytes, big-endian IEEE 754)
 *   0x40        string  (varint byte-length, then raw UTF-8)
 *   0x50        array   (varint element count, then N encoded elements)
 *   0x60        object  (varint pair count, then N key-value pairs
 *                        sorted lexicographically by key bytes;
 *                        key = varint-len + raw bytes, value = tagged)
 *
 * Varint:  unsigned LEB128 (7 bits/byte, MSB=1 means more follow)
 *
 * Integer encoding selects the smallest type that fits.
 * Integers use little-endian; floats use big-endian.
 *
 * Footer:  CRC-8 (polynomial 0x07, init 0) of all preceding bytes.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>
#include "cJSON.h"

/* ---- Dynamic byte buffer ------------------------------------------------ */

typedef struct {
    uint8_t *data;
    size_t   len;
    size_t   cap;
} Buf;

static void buf_init(Buf *b) {
    b->cap  = 4096;
    b->data = (uint8_t *)malloc(b->cap);
    b->len  = 0;
}

static void buf_push(Buf *b, uint8_t v) {
    if (b->len >= b->cap) {
        b->cap *= 2;
        b->data = (uint8_t *)realloc(b->data, b->cap);
    }
    b->data[b->len++] = v;
}

static void buf_write(Buf *b, const uint8_t *src, size_t n) {
    while (b->len + n > b->cap) {
        b->cap *= 2;
        b->data = (uint8_t *)realloc(b->data, b->cap);
    }
    memcpy(b->data + b->len, src, n);
    b->len += n;
}

/* ---- Unsigned LEB128 varint --------------------------------------------- */

static void write_varint(Buf *b, uint64_t v) {
    do {
        uint8_t byte = v & 0x7F;
        v >>= 7;
        if (v) byte |= 0x80;
        buf_push(b, byte);
    } while (v);
}

static uint64_t read_varint(const uint8_t *d, size_t len, size_t *pos) {
    uint64_t result = 0;
    int shift = 0;
    while (*pos < len) {
        uint8_t byte = d[(*pos)++];
        result |= (uint64_t)(byte & 0x7F) << shift;
        if (!(byte & 0x80)) break;
        shift += 7;
    }
    return result;
}

/* ---- CRC-8 (polynomial 0x07, init 0) ----------------------------------- */

static uint8_t crc8(const uint8_t *d, size_t len) {
    uint8_t crc = 0;
    for (size_t i = 0; i < len; i++) {
        crc ^= d[i];
        for (int j = 0; j < 8; j++) {
            if (crc & 0x80)
                crc = (crc << 1) ^ 0x07;
            else
                crc <<= 1;
        }
    }
    return crc;
}

/* ---- Key sorting helper ------------------------------------------------- */

typedef struct { char *key; cJSON *val; } KV;

static int kv_cmp(const void *a, const void *b) {
    return strcmp(((const KV *)a)->key, ((const KV *)b)->key);
}

/* ---- Encode ------------------------------------------------------------- */

static void encode_value(Buf *b, const cJSON *v) {
    if (cJSON_IsNull(v)) {
        buf_push(b, 0x00);
        return;
    }
    if (cJSON_IsFalse(v)) {
        buf_push(b, 0x01);
        return;
    }
    if (cJSON_IsTrue(v)) {
        buf_push(b, 0x02);
        return;
    }
    if (cJSON_IsNumber(v)) {
        double d = v->valuedouble;
        if (floor(d) == d && !isinf(d) && !isnan(d) &&
            d >= -9007199254740992.0 && d <= 9007199254740992.0) {
            int64_t n = (int64_t)d;
            if (n >= 0 && n <= 15) {
                buf_push(b, (uint8_t)(0x10 + n));
            } else if (n >= -128 && n <= 127) {
                buf_push(b, 0x20);
                buf_push(b, (uint8_t)(int8_t)n);
            } else if (n >= -32768 && n <= 32767) {
                buf_push(b, 0x21);
                uint16_t u = (uint16_t)(int16_t)n;
                buf_push(b, u & 0xFF);
                buf_push(b, (u >> 8) & 0xFF);
            } else if (n >= -2147483648LL && n <= 2147483647LL) {
                buf_push(b, 0x22);
                uint32_t u = (uint32_t)(int32_t)n;
                for (int i = 0; i < 4; i++)
                    buf_push(b, (u >> (i * 8)) & 0xFF);
            } else {
                buf_push(b, 0x23);
                uint64_t u = (uint64_t)n;
                for (int i = 0; i < 8; i++)
                    buf_push(b, (u >> (i * 8)) & 0xFF);
            }
        } else {
            buf_push(b, 0x30);
            uint64_t bits;
            memcpy(&bits, &d, 8);
            /* Store as big-endian */
            for (int i = 7; i >= 0; i--)
                buf_push(b, (bits >> (i * 8)) & 0xFF);
        }
        return;
    }
    if (cJSON_IsString(v)) {
        buf_push(b, 0x40);
        size_t slen = strlen(v->valuestring);
        write_varint(b, slen);
        buf_write(b, (const uint8_t *)v->valuestring, slen);
        return;
    }
    if (cJSON_IsArray(v)) {
        buf_push(b, 0x50);
        int count = cJSON_GetArraySize(v);
        write_varint(b, (uint64_t)count);
        cJSON *item;
        cJSON_ArrayForEach(item, v) {
            encode_value(b, item);
        }
        return;
    }
    if (cJSON_IsObject(v)) {
        buf_push(b, 0x60);
        int count = cJSON_GetArraySize(v);
        write_varint(b, (uint64_t)count);

        KV *kvs = (KV *)malloc(count * sizeof(KV));
        int idx = 0;
        cJSON *item;
        cJSON_ArrayForEach(item, v) {
            kvs[idx].key = item->string;
            kvs[idx].val = item;
            idx++;
        }
        qsort(kvs, count, sizeof(KV), kv_cmp);

        for (int i = 0; i < count; i++) {
            size_t klen = strlen(kvs[i].key);
            write_varint(b, klen);
            buf_write(b, (const uint8_t *)kvs[i].key, klen);
            encode_value(b, kvs[i].val);
        }
        free(kvs);
    }
}

/* ---- Decode ------------------------------------------------------------- */

static cJSON *decode_value(const uint8_t *d, size_t len, size_t *pos) {
    if (*pos >= len) return NULL;
    uint8_t tag = d[(*pos)++];

    if (tag == 0x00) return cJSON_CreateNull();
    if (tag == 0x01) return cJSON_CreateFalse();
    if (tag == 0x02) return cJSON_CreateTrue();

    if (tag >= 0x10 && tag <= 0x1F)
        return cJSON_CreateNumber((double)(tag - 0x10));

    if (tag == 0x20) {
        int8_t n = (int8_t)d[(*pos)++];
        return cJSON_CreateNumber((double)n);
    }
    if (tag == 0x21) {
        uint16_t u = d[*pos] | ((uint16_t)d[*pos + 1] << 8);
        *pos += 2;
        return cJSON_CreateNumber((double)(int16_t)u);
    }
    if (tag == 0x22) {
        uint32_t u = 0;
        for (int i = 0; i < 4; i++) u |= (uint32_t)d[*pos + i] << (i * 8);
        *pos += 4;
        return cJSON_CreateNumber((double)(int32_t)u);
    }
    if (tag == 0x23) {
        uint64_t u = 0;
        for (int i = 0; i < 8; i++) u |= (uint64_t)d[*pos + i] << (i * 8);
        *pos += 8;
        return cJSON_CreateNumber((double)(int64_t)u);
    }
    if (tag == 0x30) {
        uint64_t bits = 0;
        for (int i = 0; i < 8; i++)
            bits = (bits << 8) | d[*pos + i];
        *pos += 8;
        double dv;
        memcpy(&dv, &bits, 8);
        return cJSON_CreateNumber(dv);
    }
    if (tag == 0x40) {
        uint64_t slen = read_varint(d, len, pos);
        char *s = (char *)malloc(slen + 1);
        memcpy(s, d + *pos, slen);
        s[slen] = '\0';
        *pos += slen;
        cJSON *r = cJSON_CreateString(s);
        free(s);
        return r;
    }
    if (tag == 0x50) {
        uint64_t count = read_varint(d, len, pos);
        cJSON *arr = cJSON_CreateArray();
        for (uint64_t i = 0; i < count; i++) {
            cJSON *item = decode_value(d, len, pos);
            if (item) cJSON_AddItemToArray(arr, item);
        }
        return arr;
    }
    if (tag == 0x60) {
        uint64_t count = read_varint(d, len, pos);
        cJSON *obj = cJSON_CreateObject();
        for (uint64_t i = 0; i < count; i++) {
            uint64_t klen = read_varint(d, len, pos);
            char *key = (char *)malloc(klen + 1);
            memcpy(key, d + *pos, klen);
            key[klen] = '\0';
            *pos += klen;
            cJSON *val = decode_value(d, len, pos);
            if (val) cJSON_AddItemToObject(obj, key, val);
            free(key);
        }
        return obj;
    }
    return NULL;
}

/* ---- Custom compact JSON printer ---------------------------------------- */

static void print_json(FILE *f, const cJSON *v) {
    if (cJSON_IsNull(v)) {
        fprintf(f, "null");
        return;
    }
    if (cJSON_IsFalse(v)) {
        fprintf(f, "false");
        return;
    }
    if (cJSON_IsTrue(v)) {
        fprintf(f, "true");
        return;
    }
    if (cJSON_IsNumber(v)) {
        double d = v->valuedouble;
        if (floor(d) == d && !isinf(d) && !isnan(d) &&
            fabs(d) <= 9007199254740992.0) {
            fprintf(f, "%lld", (long long)(int64_t)d);
        } else {
            char buf[64];
            snprintf(buf, sizeof(buf), "%.17g", d);
            fprintf(f, "%s", buf);
        }
        return;
    }
    if (cJSON_IsString(v)) {
        fputc('"', f);
        const char *s = v->valuestring;
        while (*s) {
            unsigned char c = (unsigned char)*s;
            switch (c) {
                case '"':  fprintf(f, "\\\""); break;
                case '\\': fprintf(f, "\\\\"); break;
                case '\n': fprintf(f, "\\n");  break;
                case '\r': fprintf(f, "\\r");  break;
                case '\t': fprintf(f, "\\t");  break;
                case '\b': fprintf(f, "\\b");  break;
                case '\f': fprintf(f, "\\f");  break;
                default:
                    if (c < 0x20)
                        fprintf(f, "\\u%04x", c);
                    else
                        fputc(c, f);
            }
            s++;
        }
        fputc('"', f);
        return;
    }
    if (cJSON_IsArray(v)) {
        fputc('[', f);
        cJSON *item = v->child;
        int first = 1;
        while (item) {
            if (!first) fputc(',', f);
            print_json(f, item);
            first = 0;
            item = item->next;
        }
        fputc(']', f);
        return;
    }
    if (cJSON_IsObject(v)) {
        fputc('{', f);
        cJSON *item = v->child;
        int first = 1;
        while (item) {
            if (!first) fputc(',', f);
            /* Print key with escaping */
            fputc('"', f);
            const char *s = item->string;
            while (*s) {
                unsigned char c = (unsigned char)*s;
                switch (c) {
                    case '"':  fprintf(f, "\\\""); break;
                    case '\\': fprintf(f, "\\\\"); break;
                    case '\n': fprintf(f, "\\n");  break;
                    case '\r': fprintf(f, "\\r");  break;
                    case '\t': fprintf(f, "\\t");  break;
                    default:
                        if (c < 0x20)
                            fprintf(f, "\\u%04x", c);
                        else
                            fputc(c, f);
                }
                s++;
            }
            fprintf(f, "\":");
            print_json(f, item);
            first = 0;
            item = item->next;
        }
        fputc('}', f);
    }
}

/* ---- Dump internal diagnostic tables ------------------------------------ */

static void cmd_dump_tables(void) {
    /* Generate CRC-8 lookup table */
    uint8_t table[256];
    for (int i = 0; i < 256; i++) {
        uint8_t crc = (uint8_t)i;
        for (int j = 0; j < 8; j++) {
            if (crc & 0x80)
                crc = (crc << 1) ^ 0x07;
            else
                crc <<= 1;
        }
        table[i] = crc;
    }

    printf("RPACK v1 Internal Diagnostics\n");
    printf("=============================\n\n");
    printf("Integrity Algorithm: CRC-8\n");
    printf("  polynomial: 0x07\n");
    printf("  init:       0x00\n");
    printf("  xor_out:    0x00\n");
    printf("  reflect:    none\n\n");
    printf("CRC-8 Lookup Table (256 entries):\n");
    for (int i = 0; i < 256; i++) {
        if (i % 16 == 0) printf("  %02x:", i);
        printf(" %02x", table[i]);
        if (i % 16 == 15) printf("\n");
    }
    printf("\nType Tag Map:\n");
    printf("  0x00       null\n");
    printf("  0x01       boolean_false\n");
    printf("  0x02       boolean_true\n");
    printf("  0x10-0x1f  fixint (value = tag & 0x0f)\n");
    printf("  0x20       int8\n");
    printf("  0x21       int16\n");
    printf("  0x22       int32\n");
    printf("  0x23       int64\n");
    printf("  0x30       float64\n");
    printf("  0x40       string\n");
    printf("  0x50       array\n");
    printf("  0x60       object\n");
}

/* ---- Read all of stdin -------------------------------------------------- */

static uint8_t *read_stdin(size_t *out_len) {
    size_t cap = 8192, len = 0;
    uint8_t *buf = (uint8_t *)malloc(cap);
    size_t n;
    while ((n = fread(buf + len, 1, cap - len, stdin)) > 0) {
        len += n;
        if (len >= cap) {
            cap *= 2;
            buf = (uint8_t *)realloc(buf, cap);
        }
    }
    /* Null-terminate for JSON parsing */
    if (len >= cap) {
        cap++;
        buf = (uint8_t *)realloc(buf, cap);
    }
    buf[len] = '\0';
    *out_len = len;
    return buf;
}

/* ---- Main --------------------------------------------------------------- */

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s encode|decode|validate\n", argv[0]);
        return 1;
    }

    if (strcmp(argv[1], "encode") == 0) {
        size_t ilen;
        uint8_t *input = read_stdin(&ilen);

        cJSON *json = cJSON_ParseWithLength((const char *)input, ilen);
        if (!json) {
            fprintf(stderr, "Error: invalid JSON\n");
            free(input);
            return 1;
        }

        Buf b;
        buf_init(&b);
        buf_push(&b, 0xCF);
        buf_push(&b, 0xB0);
        buf_push(&b, 0x01);
        encode_value(&b, json);
        buf_push(&b, crc8(b.data, b.len));

        fwrite(b.data, 1, b.len, stdout);

        cJSON_Delete(json);
        free(b.data);
        free(input);

    } else if (strcmp(argv[1], "decode") == 0) {
        size_t ilen;
        uint8_t *input = read_stdin(&ilen);

        if (ilen < 4 || input[0] != 0xCF || input[1] != 0xB0 || input[2] != 0x01) {
            fprintf(stderr, "Error: invalid header\n");
            free(input);
            return 1;
        }

        uint8_t expected = input[ilen - 1];
        uint8_t actual   = crc8(input, ilen - 1);
        if (expected != actual) {
            fprintf(stderr, "Error: CRC mismatch\n");
            free(input);
            return 1;
        }

        size_t pos = 3;
        cJSON *json = decode_value(input, ilen - 1, &pos);
        if (!json) {
            fprintf(stderr, "Error: decode failed\n");
            free(input);
            return 1;
        }

        print_json(stdout, json);
        fputc('\n', stdout);

        cJSON_Delete(json);
        free(input);

    } else if (strcmp(argv[1], "validate") == 0) {
        size_t ilen;
        uint8_t *input = read_stdin(&ilen);

        if (ilen < 4 || input[0] != 0xCF || input[1] != 0xB0 || input[2] != 0x01) {
            printf("INVALID: bad header\n");
            free(input);
            return 0;
        }

        uint8_t expected = input[ilen - 1];
        uint8_t actual   = crc8(input, ilen - 1);
        if (expected != actual) {
            printf("INVALID: CRC mismatch\n");
            free(input);
            return 0;
        }

        size_t pos = 3;
        cJSON *json = decode_value(input, ilen - 1, &pos);
        if (!json) {
            printf("INVALID: decode error\n");
            free(input);
            return 0;
        }

        if (pos != ilen - 1) {
            printf("INVALID: trailing data\n");
            cJSON_Delete(json);
            free(input);
            return 0;
        }

        printf("VALID\n");
        cJSON_Delete(json);
        free(input);

    } else if (strcmp(argv[1], "dump-tables") == 0) {
        cmd_dump_tables();

    } else {
        fprintf(stderr, "Unknown command: %s\n", argv[1]);
        return 1;
    }

    return 0;
}
