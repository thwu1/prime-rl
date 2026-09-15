/*
 * COBS (Consistent Overhead Byte Stuffing) reference encoder/decoder.
 *
 * Usage:
 *   cobs_ref encode       — read binary from stdin, write COBS-encoded to stdout
 *   cobs_ref decode       — read COBS from stdin, write decoded binary to stdout
 *   cobs_ref gen-vectors DIR — generate binary test vector files in DIR
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <sys/types.h>

#define MAX_BUF 131072

static size_t cobs_encode(const uint8_t *input, size_t input_len,
                          uint8_t *output, size_t output_max)
{
    size_t out_idx = 0;
    size_t code_idx = out_idx++;
    uint8_t count = 1;

    for (size_t i = 0; i < input_len; i++) {
        if (input[i] == 0x00) {
            output[code_idx] = count;
            count = 1;
            code_idx = out_idx++;
        } else {
            output[out_idx++] = input[i];
            count++;
            if (count == 0xFF) {
                output[code_idx] = 0xFF;
                count = 1;
                code_idx = out_idx++;
            }
        }
    }
    output[code_idx] = count;
    return out_idx;
}

static ssize_t cobs_decode(const uint8_t *input, size_t input_len,
                           uint8_t *output, size_t output_max)
{
    size_t out_idx = 0;
    size_t idx = 0;

    while (idx < input_len) {
        uint8_t code = input[idx++];
        if (code == 0) return -1;

        for (uint8_t i = 1; i < code; i++) {
            if (idx >= input_len) return -1;
            output[out_idx++] = input[idx++];
        }

        if (code < 0xFF && idx < input_len) {
            output[out_idx++] = 0x00;
        }
    }
    return (ssize_t)out_idx;
}

static void write_u32_le(FILE *f, uint32_t v)
{
    uint8_t buf[4];
    buf[0] = v & 0xFF;
    buf[1] = (v >> 8) & 0xFF;
    buf[2] = (v >> 16) & 0xFF;
    buf[3] = (v >> 24) & 0xFF;
    fwrite(buf, 1, 4, f);
}

static void write_vector_pair(FILE *f,
                              const uint8_t *orig, size_t orig_len,
                              uint8_t *enc_buf, size_t enc_buf_max)
{
    size_t enc_len = cobs_encode(orig, orig_len, enc_buf, enc_buf_max);
    write_u32_le(f, (uint32_t)orig_len);
    fwrite(orig, 1, orig_len, f);
    write_u32_le(f, (uint32_t)enc_len);
    fwrite(enc_buf, 1, enc_len, f);
}

static void gen_vectors(const char *dir)
{
    uint8_t enc_buf[MAX_BUF];
    char path[512];

    /* === cobs_vectors.bin: pairs of (orig_len, orig, enc_len, encoded) === */
    snprintf(path, sizeof(path), "%s/cobs_vectors.bin", dir);
    FILE *f = fopen(path, "wb");
    if (!f) { perror("fopen cobs_vectors.bin"); exit(1); }

    /* 1. empty */
    write_vector_pair(f, (uint8_t[]){0}, 0, enc_buf, sizeof(enc_buf));

    /* 2. single zero */
    { uint8_t d[] = {0x00};
      write_vector_pair(f, d, 1, enc_buf, sizeof(enc_buf)); }

    /* 3. double zero */
    { uint8_t d[] = {0x00, 0x00};
      write_vector_pair(f, d, 2, enc_buf, sizeof(enc_buf)); }

    /* 4. non-zero only */
    { uint8_t d[] = {0x11, 0x22, 0x33, 0x44};
      write_vector_pair(f, d, 4, enc_buf, sizeof(enc_buf)); }

    /* 5. mixed */
    { uint8_t d[] = {0x11, 0x22, 0x00, 0x33};
      write_vector_pair(f, d, 4, enc_buf, sizeof(enc_buf)); }

    /* 6. trailing zeros */
    { uint8_t d[] = {0x11, 0x00, 0x00, 0x00};
      write_vector_pair(f, d, 4, enc_buf, sizeof(enc_buf)); }

    /* 7. bytes 0x01..0xFE (254 non-zero) */
    { uint8_t d[254];
      for (int i = 0; i < 254; i++) d[i] = (uint8_t)(i + 1);
      write_vector_pair(f, d, 254, enc_buf, sizeof(enc_buf)); }

    /* 8. bytes 0x00..0xFE (zero then 254 non-zero) */
    { uint8_t d[255];
      for (int i = 0; i < 255; i++) d[i] = (uint8_t)i;
      write_vector_pair(f, d, 255, enc_buf, sizeof(enc_buf)); }

    /* 9. bytes 0x01..0xFF (255 non-zero, crosses 254-byte boundary) */
    { uint8_t d[255];
      for (int i = 0; i < 255; i++) d[i] = (uint8_t)(i + 1);
      write_vector_pair(f, d, 255, enc_buf, sizeof(enc_buf)); }

    /* 10. bytes 0x02..0xFF then 0x00 */
    { uint8_t d[255];
      for (int i = 0; i < 254; i++) d[i] = (uint8_t)(i + 2);
      d[254] = 0x00;
      write_vector_pair(f, d, 255, enc_buf, sizeof(enc_buf)); }

    /* 11. all-zero runs of various lengths */
    { uint8_t d[50];
      memset(d, 0, 50);
      write_vector_pair(f, d, 50, enc_buf, sizeof(enc_buf)); }

    /* 12. alternating 0x00 and 0xFF */
    { uint8_t d[100];
      for (int i = 0; i < 100; i++) d[i] = (i % 2 == 0) ? 0x00 : 0xFF;
      write_vector_pair(f, d, 100, enc_buf, sizeof(enc_buf)); }

    /* 13. exactly 508 non-zero bytes (2 full 254-byte blocks) */
    { uint8_t d[508];
      for (int i = 0; i < 508; i++) d[i] = (uint8_t)((i % 254) + 1);
      write_vector_pair(f, d, 508, enc_buf, sizeof(enc_buf)); }

    /* 14. 600 bytes of 0xAA (multiple boundary crossings) */
    { uint8_t d[600];
      memset(d, 0xAA, 600);
      write_vector_pair(f, d, 600, enc_buf, sizeof(enc_buf)); }

    fclose(f);

    /* === framed_stream.bin: COBS-framed stream with 0x00 sentinels === */
    snprintf(path, sizeof(path), "%s/framed_stream.bin", dir);
    f = fopen(path, "wb");
    if (!f) { perror("fopen framed_stream.bin"); exit(1); }

    uint8_t sentinel = 0x00;

    /* Message 1: [0x01, 0x02, 0x03] */
    { uint8_t d[] = {0x01, 0x02, 0x03};
      size_t n = cobs_encode(d, 3, enc_buf, sizeof(enc_buf));
      fwrite(enc_buf, 1, n, f);
      fwrite(&sentinel, 1, 1, f); }

    /* Message 2: [0x00] */
    { uint8_t d[] = {0x00};
      size_t n = cobs_encode(d, 1, enc_buf, sizeof(enc_buf));
      fwrite(enc_buf, 1, n, f);
      fwrite(&sentinel, 1, 1, f); }

    /* Message 3: [0xFF] * 300 */
    { uint8_t d[300];
      memset(d, 0xFF, 300);
      size_t n = cobs_encode(d, 300, enc_buf, sizeof(enc_buf));
      fwrite(enc_buf, 1, n, f);
      fwrite(&sentinel, 1, 1, f); }

    /* Message 4: empty */
    { size_t n = cobs_encode(NULL, 0, enc_buf, sizeof(enc_buf));
      fwrite(enc_buf, 1, n, f);
      fwrite(&sentinel, 1, 1, f); }

    fclose(f);

    fprintf(stderr, "Generated vectors in %s\n", dir);
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr,
            "Usage: cobs_ref <encode|decode|gen-vectors [dir]>\n");
        return 1;
    }

    if (strcmp(argv[1], "encode") == 0) {
        uint8_t *input = malloc(MAX_BUF);
        uint8_t *output = malloc(MAX_BUF);
        size_t input_len = fread(input, 1, MAX_BUF, stdin);
        size_t output_len = cobs_encode(input, input_len, output, MAX_BUF);
        fwrite(output, 1, output_len, stdout);
        free(input); free(output);
    } else if (strcmp(argv[1], "decode") == 0) {
        uint8_t *input = malloc(MAX_BUF);
        uint8_t *output = malloc(MAX_BUF);
        size_t input_len = fread(input, 1, MAX_BUF, stdin);
        ssize_t output_len = cobs_decode(input, input_len, output, MAX_BUF);
        if (output_len < 0) {
            fprintf(stderr, "COBS decode error\n");
            free(input); free(output);
            return 1;
        }
        fwrite(output, 1, (size_t)output_len, stdout);
        free(input); free(output);
    } else if (strcmp(argv[1], "gen-vectors") == 0) {
        const char *dir = (argc >= 3) ? argv[2] : ".";
        gen_vectors(dir);
    } else {
        fprintf(stderr, "Unknown command: %s\n", argv[1]);
        return 1;
    }

    return 0;
}
