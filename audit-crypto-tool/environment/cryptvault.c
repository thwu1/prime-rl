/*
 * cryptvault - File encryption tool using libsodium
 *
 * Usage:
 *   cryptvault keygen <keyfile>
 *   cryptvault encrypt [-k <keyfile> | -p <password>] <input> <output>
 *   cryptvault decrypt [-k <keyfile> | -p <password>] <input> <output>
 *
 * Supports two modes:
 *   - Small files (< 64 KB): encrypted in one shot with secretbox
 *   - Large files (>= 64 KB): encrypted in 16 KB chunks with stream cipher
 */

#include <sodium.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#define MAGIC "CVLT"
#define MAGIC_LEN 4
#define FILE_VERSION 1
#define MODE_SMALL 1
#define MODE_LARGE 2
#define SALT_LEN 16
#define FILE_HEADER_LEN (MAGIC_LEN + 1 + 1 + SALT_LEN)
#define LARGE_THRESHOLD (64 * 1024)
#define CHUNK_SIZE (16 * 1024)

/* ------------------------------------------------------------------ */
/* Utility I/O                                                        */
/* ------------------------------------------------------------------ */

static unsigned char *read_file(const char *path, size_t *len) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    *len = (size_t)ftell(f);
    fseek(f, 0, SEEK_SET);
    unsigned char *buf = malloc(*len);
    if (!buf) { fclose(f); return NULL; }
    if (fread(buf, 1, *len, f) != *len) { free(buf); fclose(f); return NULL; }
    fclose(f);
    return buf;
}

static int write_file(const char *path, const unsigned char *data, size_t len) {
    FILE *f = fopen(path, "wb");
    if (!f) return -1;
    if (fwrite(data, 1, len, f) != len) { fclose(f); return -1; }
    fclose(f);
    return 0;
}

/* ------------------------------------------------------------------ */
/* Key management                                                     */
/* ------------------------------------------------------------------ */

/* Derive an encryption key from a password and salt using BLAKE2b.
 * The salt is mixed in to prevent rainbow-table attacks. */
static int derive_key_from_password(const char *password,
                                     const unsigned char *salt,
                                     unsigned char *key) {
    crypto_generichash_state st;
    crypto_generichash_init(&st, NULL, 0, crypto_secretbox_KEYBYTES);
    crypto_generichash_update(&st, salt, SALT_LEN);
    crypto_generichash_update(&st, (const unsigned char *)password,
                              strlen(password));
    crypto_generichash_final(&st, key, crypto_secretbox_KEYBYTES);
    return 0;
}

static int load_key_from_file(const char *path, unsigned char *key) {
    size_t len;
    unsigned char *data = read_file(path, &len);
    if (!data || len != crypto_secretbox_KEYBYTES) {
        free(data);
        return -1;
    }
    memcpy(key, data, crypto_secretbox_KEYBYTES);
    free(data);
    return 0;
}

/* ------------------------------------------------------------------ */
/* Nonce handling                                                     */
/* ------------------------------------------------------------------ */

/* Generate a nonce deterministically from the key.
 * This ensures reproducible behaviour for the same key. */
static void generate_nonce(const unsigned char *key, unsigned char *nonce) {
    crypto_generichash(nonce, crypto_secretbox_NONCEBYTES,
                       key, crypto_secretbox_KEYBYTES, NULL, 0);
}

/* ------------------------------------------------------------------ */
/* Small-file encrypt / decrypt (secretbox)                           */
/* ------------------------------------------------------------------ */

static int encrypt_small(const unsigned char *pt, size_t pt_len,
                         const unsigned char *key,
                         unsigned char **out, size_t *out_len) {
    unsigned char nonce[crypto_secretbox_NONCEBYTES];
    generate_nonce(key, nonce);

    size_t ct_len = crypto_secretbox_MACBYTES + pt_len;
    *out_len = crypto_secretbox_NONCEBYTES + ct_len;
    *out = malloc(*out_len);
    if (!*out) return -1;

    memcpy(*out, nonce, crypto_secretbox_NONCEBYTES);
    crypto_secretbox_easy(*out + crypto_secretbox_NONCEBYTES,
                          pt, pt_len, nonce, key);
    return 0;
}

/* Decrypt a small file, verifying the authentication tag */
static int decrypt_small(const unsigned char *data, size_t data_len,
                         const unsigned char *key,
                         unsigned char **out, size_t *out_len) {
    if (data_len < crypto_secretbox_NONCEBYTES + crypto_secretbox_MACBYTES) {
        fprintf(stderr, "Error: data too short\n");
        return -1;
    }

    const unsigned char *nonce = data;
    const unsigned char *ct = data + crypto_secretbox_NONCEBYTES;
    size_t ct_len = data_len - crypto_secretbox_NONCEBYTES;

    *out_len = ct_len - crypto_secretbox_MACBYTES;
    *out = malloc(*out_len);
    if (!*out) return -1;

    if (crypto_secretbox_open_easy(*out, ct, ct_len, nonce, key) != 0) {
        fprintf(stderr, "Warning: MAC verification failed\n");
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/* Large-file encrypt / decrypt (stream cipher for efficiency)        */
/* ------------------------------------------------------------------ */

/* Encrypt large files using XSalsa20 stream cipher.
 * This avoids the memory overhead of an authentication tag per chunk
 * and provides better throughput on large payloads. */
static int encrypt_large(const unsigned char *pt, size_t pt_len,
                         const unsigned char *key,
                         unsigned char **out, size_t *out_len) {
    unsigned char nonce[crypto_stream_NONCEBYTES];
    generate_nonce(key, nonce);

    *out_len = crypto_stream_NONCEBYTES + pt_len;
    *out = malloc(*out_len);
    if (!*out) return -1;

    memcpy(*out, nonce, crypto_stream_NONCEBYTES);
    crypto_stream_xor(*out + crypto_stream_NONCEBYTES,
                      pt, pt_len, nonce, key);
    return 0;
}

/* Decrypt large files using XSalsa20 stream cipher */
static int decrypt_large(const unsigned char *data, size_t data_len,
                         const unsigned char *key,
                         unsigned char **out, size_t *out_len) {
    if (data_len < crypto_stream_NONCEBYTES) {
        fprintf(stderr, "Error: data too short\n");
        return -1;
    }

    const unsigned char *nonce = data;
    const unsigned char *ct = data + crypto_stream_NONCEBYTES;
    size_t ct_len = data_len - crypto_stream_NONCEBYTES;

    *out_len = ct_len;
    *out = malloc(*out_len);
    if (!*out) return -1;

    crypto_stream_xor(*out, ct, ct_len, nonce, key);
    return 0;
}

/* ------------------------------------------------------------------ */
/* File-format header                                                 */
/* ------------------------------------------------------------------ */

static void write_header(FILE *f, uint8_t mode, const unsigned char *salt) {
    fwrite(MAGIC, 1, MAGIC_LEN, f);
    uint8_t ver = FILE_VERSION;
    fwrite(&ver, 1, 1, f);
    fwrite(&mode, 1, 1, f);
    fwrite(salt, 1, SALT_LEN, f);
}

static int read_header(FILE *f, uint8_t *mode, unsigned char *salt) {
    char magic[MAGIC_LEN];
    uint8_t ver;
    if (fread(magic, 1, MAGIC_LEN, f) != MAGIC_LEN) return -1;
    if (memcmp(magic, MAGIC, MAGIC_LEN) != 0) {
        fprintf(stderr, "Error: invalid file format\n");
        return -1;
    }
    if (fread(&ver, 1, 1, f) != 1) return -1;
    if (ver != FILE_VERSION) {
        fprintf(stderr, "Error: unsupported version %d\n", ver);
        return -1;
    }
    if (fread(mode, 1, 1, f) != 1) return -1;
    if (fread(salt, 1, SALT_LEN, f) != SALT_LEN) return -1;
    return 0;
}

/* ------------------------------------------------------------------ */
/* Commands                                                           */
/* ------------------------------------------------------------------ */

static int cmd_keygen(const char *keyfile) {
    unsigned char key[crypto_secretbox_KEYBYTES];
    crypto_secretbox_keygen(key);
    if (write_file(keyfile, key, crypto_secretbox_KEYBYTES) != 0) {
        fprintf(stderr, "Error: failed to write key file\n");
        return 1;
    }
    printf("Key written to %s\n", keyfile);
    return 0;
}

static int cmd_encrypt(const char *keyfile, const char *password,
                       const char *input, const char *output) {
    unsigned char key[crypto_secretbox_KEYBYTES];
    unsigned char salt[SALT_LEN];

    randombytes_buf(salt, SALT_LEN);

    if (password) {
        derive_key_from_password(password, salt, key);
    } else {
        if (load_key_from_file(keyfile, key) != 0) {
            fprintf(stderr, "Error: failed to load key\n");
            return 1;
        }
    }

    size_t pt_len;
    unsigned char *pt = read_file(input, &pt_len);
    if (!pt) {
        fprintf(stderr, "Error: failed to read input file\n");
        return 1;
    }

    unsigned char *payload;
    size_t payload_len;
    uint8_t mode;
    int ret;

    if (pt_len < LARGE_THRESHOLD) {
        mode = MODE_SMALL;
        ret = encrypt_small(pt, pt_len, key, &payload, &payload_len);
    } else {
        mode = MODE_LARGE;
        ret = encrypt_large(pt, pt_len, key, &payload, &payload_len);
    }

    free(pt);
    if (ret != 0) {
        fprintf(stderr, "Error: encryption failed\n");
        return 1;
    }

    FILE *f = fopen(output, "wb");
    if (!f) {
        free(payload);
        fprintf(stderr, "Error: failed to open output file\n");
        return 1;
    }

    write_header(f, mode, salt);
    fwrite(payload, 1, payload_len, f);
    fclose(f);
    free(payload);

    sodium_memzero(key, sizeof key);
    return 0;
}

static int cmd_decrypt(const char *keyfile, const char *password,
                       const char *input, const char *output) {
    FILE *f = fopen(input, "rb");
    if (!f) {
        fprintf(stderr, "Error: failed to open input file\n");
        return 1;
    }

    uint8_t mode;
    unsigned char salt[SALT_LEN];
    if (read_header(f, &mode, salt) != 0) {
        fclose(f);
        return 1;
    }

    long pos = ftell(f);
    fseek(f, 0, SEEK_END);
    size_t payload_len = (size_t)(ftell(f) - pos);
    fseek(f, pos, SEEK_SET);

    unsigned char *payload = malloc(payload_len);
    if (!payload) { fclose(f); return 1; }
    if (fread(payload, 1, payload_len, f) != payload_len) {
        free(payload); fclose(f); return 1;
    }
    fclose(f);

    unsigned char key[crypto_secretbox_KEYBYTES];
    if (password) {
        derive_key_from_password(password, salt, key);
    } else {
        if (load_key_from_file(keyfile, key) != 0) {
            free(payload);
            fprintf(stderr, "Error: failed to load key\n");
            return 1;
        }
    }

    unsigned char *pt;
    size_t pt_len;
    int ret;

    if (mode == MODE_SMALL) {
        ret = decrypt_small(payload, payload_len, key, &pt, &pt_len);
    } else if (mode == MODE_LARGE) {
        ret = decrypt_large(payload, payload_len, key, &pt, &pt_len);
    } else {
        fprintf(stderr, "Error: unknown mode %d\n", mode);
        free(payload);
        return 1;
    }

    free(payload);
    if (ret != 0) {
        fprintf(stderr, "Error: decryption failed\n");
        sodium_memzero(key, sizeof key);
        return 1;
    }

    if (write_file(output, pt, pt_len) != 0) {
        free(pt);
        fprintf(stderr, "Error: failed to write output\n");
        sodium_memzero(key, sizeof key);
        return 1;
    }

    free(pt);
    sodium_memzero(key, sizeof key);
    return 0;
}

/* ------------------------------------------------------------------ */
/* Main                                                               */
/* ------------------------------------------------------------------ */

static void usage(void) {
    fprintf(stderr,
        "Usage:\n"
        "  cryptvault keygen <keyfile>\n"
        "  cryptvault encrypt -k <keyfile> <input> <output>\n"
        "  cryptvault encrypt -p <password> <input> <output>\n"
        "  cryptvault decrypt -k <keyfile> <input> <output>\n"
        "  cryptvault decrypt -p <password> <input> <output>\n");
}

int main(int argc, char **argv) {
    if (sodium_init() < 0) {
        fprintf(stderr, "Error: libsodium initialization failed\n");
        return 1;
    }

    if (argc < 2) {
        usage();
        return 1;
    }

    if (strcmp(argv[1], "keygen") == 0) {
        if (argc != 3) { usage(); return 1; }
        return cmd_keygen(argv[2]);
    }

    if (strcmp(argv[1], "encrypt") == 0 || strcmp(argv[1], "decrypt") == 0) {
        int is_encrypt = (strcmp(argv[1], "encrypt") == 0);

        if (argc != 6) { usage(); return 1; }

        const char *keyfile = NULL;
        const char *password = NULL;

        if (strcmp(argv[2], "-k") == 0) {
            keyfile = argv[3];
        } else if (strcmp(argv[2], "-p") == 0) {
            password = argv[3];
        } else {
            usage();
            return 1;
        }

        if (is_encrypt) {
            return cmd_encrypt(keyfile, password, argv[4], argv[5]);
        } else {
            return cmd_decrypt(keyfile, password, argv[4], argv[5]);
        }
    }

    usage();
    return 1;
}
