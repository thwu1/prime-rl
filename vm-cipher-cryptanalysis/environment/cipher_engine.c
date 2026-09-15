/*
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

static uint32_t g_state;

static void prng_seed(uint32_t v) {
    g_state = v ^ 0xA3B1C6D9u;
}

static uint32_t prng_next(void) {
    g_state = g_state * 0x41C64E6Du + 0x3039u;
    return g_state;
}

static void derive_key(uint32_t seed, uint8_t key[16]) {
    prng_seed(seed);
    for (int i = 0; i < 16; i++) {
        key[i] = (uint8_t)((prng_next() >> 16) & 0xFF);
    }
}

static uint32_t read_be32(const uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8)  | (uint32_t)p[3];
}

static void write_be32(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)(v >> 24);
    p[1] = (uint8_t)(v >> 16);
    p[2] = (uint8_t)(v >> 8);
    p[3] = (uint8_t)v;
}

static uint32_t round_fn(uint32_t x, uint32_t k) {
    x = ((x >> 5) | (x << 27));
    x ^= k;
    x *= 0x9E3779B9u;
    x ^= (x >> 16);
    return x;
}

static uint32_t make_subkey(const uint8_t key[16], int r) {
    return ((uint32_t)key[r & 0xF] << 24) |
           ((uint32_t)key[(r * 3 + 1) & 0xF] << 16) |
           ((uint32_t)key[(r * 5 + 2) & 0xF] << 8) |
           (uint32_t)key[(r * 7 + 3) & 0xF];
}

static void encrypt_block(uint8_t blk[8], const uint8_t key[16]) {
    uint32_t L = read_be32(blk);
    uint32_t R = read_be32(blk + 4);
    for (int i = 0; i < 16; i++) {
        uint32_t sk = make_subkey(key, i);
        uint32_t t = L ^ round_fn(R, sk);
        L = R;
        R = t;
    }
    write_be32(blk, L);
    write_be32(blk + 4, R);
}

static void decrypt_block(uint8_t blk[8], const uint8_t key[16]) {
    uint32_t L = read_be32(blk);
    uint32_t R = read_be32(blk + 4);
    for (int i = 15; i >= 0; i--) {
        uint32_t sk = make_subkey(key, i);
        uint32_t t = R ^ round_fn(L, sk);
        R = L;
        L = t;
    }
    write_be32(blk, L);
    write_be32(blk + 4, R);
}

static int process_file(const char *in_path, const char *out_path,
                        const uint8_t key[16], int enc) {
    FILE *fin = fopen(in_path, "rb");
    if (!fin) { perror("open input"); return 1; }
    fseek(fin, 0, SEEK_END);
    long fsize = ftell(fin);
    fseek(fin, 0, SEEK_SET);

    long buf_size;
    if (enc) {
        int pad = 8 - (int)(fsize % 8);
        buf_size = fsize + pad;
    } else {
        if (fsize % 8 != 0) {
            fprintf(stderr, "Error: ciphertext size not aligned to block size\n");
            fclose(fin);
            return 1;
        }
        buf_size = fsize;
    }

    uint8_t *buf = (uint8_t *)calloc((size_t)buf_size, 1);
    if (!buf) { perror("malloc"); fclose(fin); return 1; }
    fread(buf, 1, (size_t)fsize, fin);
    fclose(fin);

    if (enc) {
        int pad = (int)(buf_size - fsize);
        for (long i = fsize; i < buf_size; i++)
            buf[i] = (uint8_t)pad;
    }

    for (long i = 0; i < buf_size; i += 8) {
        if (enc)
            encrypt_block(buf + i, key);
        else
            decrypt_block(buf + i, key);
    }

    long out_size = buf_size;
    if (!enc) {
        uint8_t pad_val = buf[buf_size - 1];
        if (pad_val >= 1 && pad_val <= 8) {
            int valid = 1;
            for (int j = 0; j < pad_val; j++) {
                if (buf[buf_size - 1 - j] != pad_val) {
                    valid = 0;
                    break;
                }
            }
            if (valid) out_size = buf_size - pad_val;
        }
    }

    FILE *fout = fopen(out_path, "wb");
    if (!fout) { perror("open output"); free(buf); return 1; }
    fwrite(buf, 1, (size_t)out_size, fout);
    fclose(fout);
    free(buf);
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr, "Usage: %s <e|d> <seed> <input> [output]\n", argv[0]);
        return 1;
    }

    int encrypt_mode = (argv[1][0] == 'e');
    uint32_t seed;
    const char *input_path;
    const char *output_path;

    if (argc >= 5 && strcmp(argv[2], "-D") == 0) {
        seed = (uint32_t)strtoul(argv[3], NULL, 0);
        seed ^= 0xB16B00B5u;
        input_path = argv[4];
        output_path = (argc > 5) ? argv[5] : (encrypt_mode ? "out.enc" : "out.dec");
    } else {
        seed = (uint32_t)strtoul(argv[2], NULL, 0);
        input_path = argv[3];
        output_path = (argc > 4) ? argv[4] : (encrypt_mode ? "out.enc" : "out.dec");
    }

    uint8_t key[16];
    derive_key(seed, key);

    return process_file(input_path, output_path, key, encrypt_mode);
}
