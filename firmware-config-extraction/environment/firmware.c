/*
 * firmware.c - Simulated IoT firmware with encrypted configuration
 * Compiled stripped, placed at /app/firmware
 *
 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

/* ===== Encrypted config data in custom ELF sections ===== */

static const unsigned char conf1_data[] __attribute__((section(".conf1"), used)) = {
    0x1E, 0x18, 0x05, 0x12, 0x15, 0x09, 0x0E, 0x67,
    0x6B, 0x6A, 0x74, 0x6A, 0x74, 0x6B, 0x74, 0x6F,
    0x6A
};
#define CONF1_LEN 17

static const unsigned char conf2_data[] __attribute__((section(".conf2"), used)) = {
    0x73, 0x7C, 0x1A, 0x1C, 0x12, 0x09, 0x32, 0x55,
    0x3C, 0x45, 0x1E, 0xF6, 0xEE, 0xE6, 0xD2, 0x93,
    0xDE, 0x8F
};
#define CONF2_LEN 18

static const unsigned char conf3_data[] __attribute__((section(".conf3"), used)) = {
    0x9F, 0xFD, 0xF7, 0xB0, 0x95, 0xE8, 0xE7, 0xD2,
    0xBF, 0x95, 0xD8, 0xDC, 0xBB, 0x9F, 0xDC, 0xDE,
    0xBD, 0x9A, 0xDA, 0xDA
};
#define CONF3_LEN 20

static const unsigned char conf4_data[] __attribute__((section(".conf4"), used)) = {
    0x28, 0x69, 0x79, 0xB8, 0xC9, 0x79, 0xC8, 0x88,
    0x68, 0xD8, 0xEF, 0xBB, 0x98, 0xAF, 0xEA, 0x88,
    0x1F, 0x3B, 0xF8, 0x6F, 0x2B, 0x19, 0xBF
};
#define CONF4_LEN 23

static const unsigned char conf5_data[] __attribute__((section(".conf5"), used)) = {
    0x25, 0x69, 0x28, 0x6F, 0x52, 0x34, 0x43, 0x1C,
    0x6E, 0x0B, 0x54, 0x63, 0x0B, 0x38, 0x67, 0x03,
    0x30, 0x03, 0x73, 0x2C, 0x18, 0x76, 0x42, 0x2E,
    0x57, 0x62, 0x53, 0x66
};
#define CONF5_LEN 28

/* ===== Obfuscated message strings (XOR 0x5A) ===== */

static const unsigned char msg_denied[] = {
    0x1C, 0x33, 0x28, 0x37, 0x2D, 0x3B, 0x28, 0x3F,
    0x7A, 0x2C, 0x68, 0x74, 0x6B, 0x74, 0x69, 0x7A,
    0x77, 0x7A, 0x1B, 0x39, 0x39, 0x3F, 0x29, 0x29,
    0x7A, 0x3E, 0x3F, 0x34, 0x33, 0x3F, 0x3E, 0x74,
    0x50
};
#define MSG_DENIED_LEN 33

static const unsigned char msg_ok[] = {
    0x19, 0x35, 0x34, 0x3C, 0x33, 0x3D, 0x2F, 0x28,
    0x3B, 0x2E, 0x33, 0x35, 0x34, 0x7A, 0x3E, 0x2F,
    0x37, 0x2A, 0x3F, 0x3E, 0x7A, 0x29, 0x2F, 0x39,
    0x39, 0x3F, 0x29, 0x29, 0x3C, 0x2F, 0x36, 0x36,
    0x23, 0x74, 0x50
};
#define MSG_OK_LEN 35

/* Admin password verified via FNV-1a hash comparison */
#define ADMIN_HASH 0x5293030AU

/* Seed constant for key derivation (entry 5) */
#define KEY_INIT 0xDEADBEEFU

/* ===== Helper: print XOR-obfuscated message ===== */
static void __attribute__((noinline)) print_msg(const unsigned char *enc, int len, unsigned char key) {
    char buf[256];
    int i;
    for (i = 0; i < len && i < 255; i++) {
        buf[i] = (char)(enc[i] ^ key);
    }
    buf[i] = '\0';
    fputs(buf, stdout);
}

/* ===== Password validation (FNV-1a) ===== */
static int __attribute__((noinline)) validate_password(const char *password) {
    unsigned int h = 0x811C9DC5U;
    const unsigned char *p = (const unsigned char *)password;
    while (*p) {
        h ^= (unsigned int)*p++;
        h *= 0x01000193U;
    }
    return h == ADMIN_HASH;
}

/* Integrity check - always returns 1 (opaque predicate) */
static int __attribute__((noinline)) check_integrity(int x) {
    int a = x * x;
    int b = (a % 7) + 1;
    volatile int c = (b * b) % 13;
    return (c > 0 || a >= 0) ? 1 : 0;
}

/* ===== Decryption Module 1: XOR with constant key ===== */
static void __attribute__((noinline)) decrypt_mod1(
    unsigned char *out, const unsigned char *data, int len)
{
    unsigned char key = 0x5A;
    int i;
    for (i = 0; i < len; i++) {
        out[i] = data[i] ^ key;
        /* Dead branch: check_integrity always returns 1 */
        if (check_integrity(i) == 0) {
            out[i] = (unsigned char)(~out[i]);
        }
    }
    out[len] = '\0';
}

/* ===== Decryption Module 2: Rolling XOR ===== */
static void __attribute__((noinline)) decrypt_mod2(
    unsigned char *out, const unsigned char *data, int len)
{
    unsigned char seed = 0x37;
    unsigned char step = 7;
    int i;
    for (i = 0; i < len; i++) {
        unsigned char k = (unsigned char)((i * step + seed) & 0xFF);
        out[i] = data[i] ^ k;
    }
    out[len] = '\0';
}

/* ===== Decryption Module 3: Multi-key XOR ===== */
static void __attribute__((noinline)) decrypt_mod3(
    unsigned char *out, const unsigned char *data, int len)
{
    static const unsigned char keys[] = {0xDE, 0xAD, 0xBE, 0xEF};
    int nkeys = 4;
    int i;
    for (i = 0; i < len; i++) {
        out[i] = data[i] ^ keys[i % nkeys];
    }
    out[len] = '\0';
}

/* ===== Decryption Module 4: Nibble-swap + XOR ===== */
static void __attribute__((noinline)) decrypt_mod4(
    unsigned char *out, const unsigned char *data, int len)
{
    unsigned char xor_key = 0x3C;
    int i;
    for (i = 0; i < len; i++) {
        unsigned char v = data[i] ^ xor_key;
        out[i] = (unsigned char)(((v << 4) & 0xF0) | ((v >> 4) & 0x0F));
    }
    out[len] = '\0';
}

/* ===== Decryption Module 5: Chained XOR (CBC-like) ===== */
static void __attribute__((noinline)) decrypt_mod5(
    unsigned char *out, const unsigned char *data, int len,
    unsigned char init_key)
{
    int i;
    out[0] = data[0] ^ init_key;
    for (i = 1; i < len; i++) {
        out[i] = data[i] ^ data[i - 1];
    }
    out[len] = '\0';
}

/* ===== Key derivation for Module 5 ===== */
static unsigned char __attribute__((noinline)) derive_key(
    const char *data, int len)
{
    unsigned int h = KEY_INIT;
    int i;
    for (i = 0; i < len; i++) {
        h = ((h * 31) + (unsigned char)data[i]) & 0xFFFFFFFF;
    }
    return (unsigned char)(h & 0xFF);
}

/* ===== Main ===== */
int main(int argc, char *argv[]) {
    unsigned char buf1[64], buf2[64], buf3[64], buf4[64], buf5[64];
    char combined[256];
    int clen;

    if (argc < 2) {
        print_msg(msg_denied, MSG_DENIED_LEN, 0x5A);
        return 1;
    }

    if (!validate_password(argv[1])) {
        print_msg(msg_denied, MSG_DENIED_LEN, 0x5A);
        return 1;
    }

    /* Decrypt configuration modules */
    decrypt_mod1(buf1, conf1_data, CONF1_LEN);
    decrypt_mod2(buf2, conf2_data, CONF2_LEN);
    decrypt_mod3(buf3, conf3_data, CONF3_LEN);
    decrypt_mod4(buf4, conf4_data, CONF4_LEN);

    /* Build combined string from modules 1-4 for key derivation */
    clen = 0;
    memcpy(combined + clen, buf1, strlen((char *)buf1));
    clen += (int)strlen((char *)buf1);
    memcpy(combined + clen, buf2, strlen((char *)buf2));
    clen += (int)strlen((char *)buf2);
    memcpy(combined + clen, buf3, strlen((char *)buf3));
    clen += (int)strlen((char *)buf3);
    memcpy(combined + clen, buf4, strlen((char *)buf4));
    clen += (int)strlen((char *)buf4);

    /* Derive final key and decrypt module 5 */
    {
        unsigned char fkey = derive_key(combined, clen);
        decrypt_mod5(buf5, conf5_data, CONF5_LEN, fkey);
    }

    /* Output decrypted configuration */
    printf("%s\n", (char *)buf1);
    printf("%s\n", (char *)buf2);
    printf("%s\n", (char *)buf3);
    printf("%s\n", (char *)buf4);
    printf("%s\n", (char *)buf5);

    print_msg(msg_ok, MSG_OK_LEN, 0x5A);

    return 0;
}
