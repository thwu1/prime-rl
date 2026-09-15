/*
 * lz4c - LZ4 Block Format CLI Tool
 *
 * Usage:
 *   lz4c compress   <input> <output>    Compress a file
 *   lz4c decompress <input> <output>    Decompress a file
 *   lz4c roundtrip  <input>             Verify compress->decompress roundtrip
 *
 * File format: 4-byte little-endian original size + raw LZ4 compressed block
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "lz4_block.h"

static uint8_t* read_file(const char* path, int* size) {
    FILE* f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long fsize = ftell(f);
    fseek(f, 0, SEEK_SET);
    *size = (int)fsize;
    uint8_t* buf = (uint8_t*)malloc(*size > 0 ? *size : 1);
    if (buf && *size > 0) {
        if (fread(buf, 1, *size, f) != (size_t)*size) {
            free(buf);
            fclose(f);
            return NULL;
        }
    }
    fclose(f);
    return buf;
}

static int write_file(const char* path, const uint8_t* data, int size) {
    FILE* f = fopen(path, "wb");
    if (!f) return -1;
    if (size > 0) fwrite(data, 1, size, f);
    fclose(f);
    return 0;
}

static int cmd_compress(const char* inpath, const char* outpath) {
    int in_size;
    uint8_t* input = read_file(inpath, &in_size);
    if (!input) { perror(inpath); return 1; }

    int bound = lz4_compress_bound(in_size);
    uint8_t* output = (uint8_t*)malloc(bound > 0 ? bound : 1);
    int comp_size = lz4_block_compress(input, output, in_size, bound);

    if (comp_size <= 0 && in_size > 0) {
        fprintf(stderr, "Compression failed\n");
        free(input); free(output);
        return 1;
    }

    /* Write: 4-byte LE original size + compressed block */
    FILE* f = fopen(outpath, "wb");
    if (!f) { perror(outpath); free(input); free(output); return 1; }
    uint32_t orig = (uint32_t)in_size;
    fwrite(&orig, 4, 1, f);
    if (comp_size > 0) fwrite(output, 1, comp_size, f);
    fclose(f);

    fprintf(stderr, "Compressed %d -> %d bytes (%.2fx)\n",
            in_size, comp_size,
            comp_size > 0 ? (double)in_size / comp_size : 0.0);

    free(input);
    free(output);
    return 0;
}

static int cmd_decompress(const char* inpath, const char* outpath) {
    int in_size;
    uint8_t* input = read_file(inpath, &in_size);
    if (!input) { perror(inpath); return 1; }
    if (in_size < 4) {
        fprintf(stderr, "Input too small (need at least 4-byte header)\n");
        free(input);
        return 1;
    }

    uint32_t orig_size;
    memcpy(&orig_size, input, 4);

    uint8_t* output = (uint8_t*)malloc(orig_size > 0 ? orig_size : 1);
    int dec_size = 0;

    if (in_size > 4 && orig_size > 0) {
        dec_size = lz4_block_decompress(input + 4, output, in_size - 4, orig_size);
        if (dec_size < 0) {
            fprintf(stderr, "Decompression failed (error %d)\n", dec_size);
            free(input); free(output);
            return 1;
        }
    }

    write_file(outpath, output, dec_size);
    fprintf(stderr, "Decompressed %d -> %d bytes\n", in_size - 4, dec_size);

    free(input);
    free(output);
    return 0;
}

static int cmd_roundtrip(const char* inpath) {
    int in_size;
    uint8_t* input = read_file(inpath, &in_size);
    if (!input) { perror(inpath); return 1; }

    int bound = lz4_compress_bound(in_size);
    uint8_t* compressed = (uint8_t*)malloc(bound > 0 ? bound : 1);
    int comp_size = lz4_block_compress(input, compressed, in_size, bound);

    if (comp_size <= 0 && in_size > 0) {
        fprintf(stderr, "Compression failed\n");
        free(input); free(compressed);
        return 1;
    }

    uint8_t* decompressed = (uint8_t*)malloc(in_size > 0 ? in_size : 1);
    int dec_size = 0;

    if (comp_size > 0) {
        dec_size = lz4_block_decompress(compressed, decompressed, comp_size, in_size);
        if (dec_size < 0) {
            fprintf(stderr, "Decompression failed (error %d)\n", dec_size);
            free(input); free(compressed); free(decompressed);
            return 1;
        }
    }

    int ok = (dec_size == in_size)
          && (in_size == 0 || memcmp(input, decompressed, in_size) == 0);

    if (!ok) {
        fprintf(stderr, "MISMATCH: original %d bytes, roundtrip %d bytes\n",
                in_size, dec_size);
        /* Show first difference */
        if (dec_size == in_size) {
            for (int i = 0; i < in_size; i++) {
                if (input[i] != decompressed[i]) {
                    fprintf(stderr, "  First diff at byte %d: expected 0x%02x got 0x%02x\n",
                            i, input[i], decompressed[i]);
                    break;
                }
            }
        }
    } else {
        fprintf(stderr, "OK: %d -> %d -> %d bytes (%.2fx)\n",
                in_size, comp_size, dec_size,
                comp_size > 0 ? (double)in_size / comp_size : 0.0);
    }

    free(input);
    free(compressed);
    free(decompressed);
    return ok ? 0 : 1;
}

int main(int argc, char* argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage:\n");
        fprintf(stderr, "  %s compress   <input> <output>\n", argv[0]);
        fprintf(stderr, "  %s decompress <input> <output>\n", argv[0]);
        fprintf(stderr, "  %s roundtrip  <input>\n", argv[0]);
        return 1;
    }

    if (strcmp(argv[1], "compress") == 0) {
        if (argc < 4) { fprintf(stderr, "Missing arguments\n"); return 1; }
        return cmd_compress(argv[2], argv[3]);
    } else if (strcmp(argv[1], "decompress") == 0) {
        if (argc < 4) { fprintf(stderr, "Missing arguments\n"); return 1; }
        return cmd_decompress(argv[2], argv[3]);
    } else if (strcmp(argv[1], "roundtrip") == 0) {
        if (argc < 3) { fprintf(stderr, "Missing arguments\n"); return 1; }
        return cmd_roundtrip(argv[2]);
    } else {
        fprintf(stderr, "Unknown command: %s\n", argv[1]);
        return 1;
    }
}
