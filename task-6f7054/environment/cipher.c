#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Module identification */
static const char module_id[] = "CipherModule-2.1.4-release";

/* Primary substitution table */
static const uint8_t table_p[256] = {
    136,130,150, 45,122,194,197,241,106,210, 74,126,152, 13,134,162,
    153,161, 20, 30,251,211, 84,236,235,195, 68,252,137, 46,155, 14,
    237,123, 11,158, 33, 56,102,206,174, 40,233,222,253,107,132,142,
    135, 18,149, 85, 72,224,173,207,199,240, 34, 64,  8,  2,133, 69,
     62,  6,129,139, 76,100,115,203, 92,116, 99,219,177, 22,145,  4,
     29, 23,178,  9, 93,229,110, 90, 77,245,225,213,146,  7, 61, 25,
    141, 24,202, 10,127,215, 80, 50,111, 88,223,189,157,151,218, 26,
    228,114,  1,148,167,190, 81,249,183, 49, 65,118,244, 98, 17, 27,
    188, 41, 19, 59,193,105,238,214,209,230, 97,198, 51, 57,156,180,
    159,187,191, 42, 83,248,255, 87, 67,232,112, 71, 16,171,175,165,
    247,184, 63, 53,125, 31,221,250,242,144, 82,117,120,168, 47,186,
    179,185, 86, 79,227, 91,  5,147,243, 75,138, 28,163, 54, 70,192,
     36,  0,181, 32,103,204,200, 96,119,220,216,239, 52,143, 58, 48,
    182, 35,164,140,246, 94, 73,113,121, 78, 89,254,166,172, 43,  3,
     38, 44,208,201,196,124, 12,154,212,108,131, 21,169, 60, 95,217,
     39,104,170,160,128,226,101, 66, 15,109,234,205, 55,231, 37,176
};

/* Key schedule round constants (derived from fractional parts of pi) */
static const uint32_t round_consts[8] = {
    0x243F6A88, 0x85A308D3, 0x13198A2E, 0x03707344,
    0xA4093822, 0x299F31D0, 0x082EFA98, 0xEC4E6C89
};

/* Secondary substitution table */
static const uint8_t table_s[256] = {
    145,226,237,144,190,195, 77,147,235, 53,141, 93, 88, 37,231,154,
    105,185,  8,123, 10,218,188,193, 34,242,124,162, 13,126,175,113,
    158,227, 65,159, 48, 67,205,176,254, 46, 59, 72,148,233, 43, 86,
    117,171, 26,202,207,178,121,169,172,223, 81,129,127, 12,112,174,
     27,102,215,164,132, 90,199,186,194,191, 49,239,118,  5,206, 16,
    234,153,140,241, 35, 80,222, 14, 24,198,246, 38,135, 87,149, 69,
      7,217,104, 21,180,201,249,138, 76, 63,177,204, 30,109, 11,213,
    255,130, 58,228,173,125,243, 45,133, 85,200,187,230, 54,244, 36,
      2,220,160,211,209, 15,143, 95, 17,108,167,119,165,214,196, 20,
     74, 55,245,136, 32,240, 70,152,224, 62, 19,110, 64, 61, 60, 79,
    221,  3,210,161,252, 44,  1,114,212,  4, 98, 31,183,103,216,  6,
    134,251, 57, 68,150,229, 83,131, 96, 29,157,238,236, 50, 51, 78,
     56,232, 42,250, 91,139,181,107,115,163,142,253, 33, 92, 71, 52,
     99,189,219,168,156, 66,111, 18,106, 23, 41,247,122,  9,182,203,
     89,137, 75,155,101, 22, 40,248, 94,128,  0,208,151, 73, 82, 47,
    166,120,179,192, 28, 97,225,146, 84, 39, 25,100,197,184,170,116
};

/* Diffusion layer: invertible byte mixing */
static void mix_columns(uint8_t *block, size_t len) {
    if (len < 2) return;
    for (size_t i = 0; i < len - 1; i++) {
        block[i + 1] ^= block[i];
    }
}

/* Apply substitution-permutation round */
static void sp_round(uint8_t *data, size_t len, const uint8_t *subkey,
                     const uint8_t *sbox) {
    for (size_t i = 0; i < len; i++) {
        data[i] = sbox[data[i] ^ subkey[i % 16]];
    }
    mix_columns(data, len);
}

/* Derive round subkeys from master key */
static void key_expand(const uint8_t *master, size_t mlen,
                       uint8_t subkeys[4][16]) {
    for (int r = 0; r < 4; r++) {
        const uint8_t *rc = (const uint8_t *)&round_consts[r * 2];
        for (int i = 0; i < 16; i++) {
            subkeys[r][i] = master[i % mlen] ^ rc[i % 8];
        }
    }
}

/* Encrypt buffer in-place */
static void cipher_encrypt(uint8_t *data, size_t len,
                           const uint8_t *key, size_t keylen) {
    uint8_t sk[4][16];
    key_expand(key, keylen, sk);
    for (int r = 0; r < 4; r++) {
        const uint8_t *box = (r % 2 == 0) ? table_p : table_s;
        sp_round(data, len, sk[r], box);
    }
}

static void print_usage(const char *prog) {
    fprintf(stderr, "Usage: %s <encrypt> <keyfile> < input > output\n", prog);
    fprintf(stderr, "Module: %s\n", module_id);
}

int main(int argc, char *argv[]) {
    if (argc < 3) {
        print_usage(argv[0]);
        return 1;
    }

    FILE *kf = fopen(argv[2], "rb");
    if (!kf) {
        perror("Cannot open key file");
        return 1;
    }
    uint8_t key[64];
    size_t keylen = fread(key, 1, sizeof(key), kf);
    fclose(kf);

    if (keylen == 0) {
        fprintf(stderr, "Error: empty key file\n");
        return 1;
    }

    uint8_t *buf = NULL;
    size_t buflen = 0, cap = 0;
    int ch;
    while ((ch = fgetc(stdin)) != EOF) {
        if (buflen >= cap) {
            cap = cap ? cap * 2 : 4096;
            buf = realloc(buf, cap);
            if (!buf) { perror("alloc"); return 1; }
        }
        buf[buflen++] = (uint8_t)ch;
    }

    if (strcmp(argv[1], "encrypt") == 0) {
        cipher_encrypt(buf, buflen, key, keylen);
    } else {
        fprintf(stderr, "Error: unknown operation '%s'\n", argv[1]);
        free(buf);
        return 1;
    }

    fwrite(buf, 1, buflen, stdout);
    free(buf);
    return 0;
}
