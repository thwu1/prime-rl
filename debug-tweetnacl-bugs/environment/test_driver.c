/* test_driver.c — exercises each TweetNaCl primitive with deterministic inputs */

#include <stdio.h>
#include <string.h>
#include "tweetnacl.h"

/* Stub: our tests supply all key material directly, so randombytes is unused */
void randombytes(unsigned char *x, unsigned long long xlen) {
    unsigned int i;
    for (i = 0; i < xlen; i++) x[i] = 0;
}

static void phex(const char *label, const unsigned char *d, int n) {
    int i;
    printf("%s=", label);
    for (i = 0; i < n; i++) printf("%02x", d[i]);
    printf("\n");
}

/* ---- Individual primitive tests ---- */

static void test_hash(void) {
    /* SHA-512("abc") — FIPS 180-4 test vector */
    unsigned char out[64];
    unsigned char msg[3] = {0x61, 0x62, 0x63};
    crypto_hash(out, msg, 3);
    phex("hash", out, 64);
}

static void test_salsa20(void) {
    unsigned char out[64], in[16], k[32], c[16];
    memset(in, 0, sizeof in);
    memset(k, 0, sizeof k);
    k[0] = 0x01;
    k[16] = 0x02;
    k[31] = 0x03;
    memcpy(c, "expand 32-byte k", 16);

    /* Test the Salsa20 core directly */
    crypto_core_salsa20(out, in, k, c);
    phex("core", out, 64);

    /* Test stream XOR (exercises the core in counter mode) */
    {
        unsigned char sout[128], smsg[128], nonce[8];
        memset(smsg, 0x42, 128);
        memset(nonce, 0, 8);
        nonce[0] = 1;
        crypto_stream_salsa20_xor(sout, smsg, 128, nonce, k);
        phex("stream", sout, 128);
    }
}

static void test_poly1305(void) {
    unsigned char out[16];
    unsigned char msg[64];
    /* Key where r[12] has bit 2 set — triggers the clamping bug */
    unsigned char key[32] = {
        0x85, 0x1f, 0xc4, 0x0c, 0x34, 0x67, 0xac, 0x0b,
        0xe0, 0x5c, 0xc2, 0x04, 0x07, 0xf3, 0xf7, 0x00,
        0x58, 0x0b, 0x3b, 0x0f, 0x94, 0x47, 0xbb, 0x1e,
        0x69, 0xd0, 0x95, 0xb5, 0x92, 0x8b, 0x6d, 0xbc
    };
    int v;
    memset(msg, 0x42, 64);
    crypto_onetimeauth(out, msg, 64, key);
    phex("auth", out, 16);

    v = crypto_onetimeauth_verify(out, msg, 64, key);
    printf("auth_v=%d\n", v);

    /* Second test with different key to ensure robustness */
    {
        unsigned char out2[16];
        unsigned char key2[32] = {
            0xff, 0xee, 0xdd, 0x0c, 0x10, 0x20, 0x30, 0x0f,
            0x40, 0x50, 0x60, 0x07, 0x14, 0x25, 0x36, 0x0a,
            0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff, 0x11, 0x22,
            0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x99, 0x00
        };
        crypto_onetimeauth(out2, msg, 64, key2);
        phex("auth2", out2, 16);
    }
}

static void test_curve25519(void) {
    /* RFC 7748 test vector: Alice's key */
    unsigned char q[32];
    unsigned char n[32] = {
        0x77, 0x07, 0x6d, 0x0a, 0x73, 0x18, 0xa5, 0x7d,
        0x3c, 0x16, 0xc1, 0x72, 0x51, 0xb2, 0x66, 0x45,
        0xdf, 0x4c, 0x2f, 0x87, 0xeb, 0xc0, 0x99, 0x2a,
        0xb1, 0x77, 0xfb, 0xa5, 0x1d, 0xb9, 0x2c, 0x2a
    };
    unsigned char p[32];
    unsigned char q2[32];
    memset(p, 0, 32);
    p[0] = 9; /* base point */

    crypto_scalarmult(q, n, p);
    phex("sm", q, 32);

    /* Also test scalarmult_base (should give same result as above) */
    crypto_scalarmult_base(q2, n);
    phex("smb", q2, 32);
}

static void test_ed25519(void) {
    /* RFC 8032 Test Vector 1: Ed25519 */
    unsigned char sk[64] = {
        /* seed */
        0x9d, 0x61, 0xb1, 0x9d, 0xef, 0xfd, 0x5a, 0x60,
        0xba, 0x84, 0x4a, 0xf4, 0x92, 0xec, 0x2c, 0xc4,
        0x44, 0x49, 0xc5, 0x69, 0x7b, 0x32, 0x69, 0x19,
        0x70, 0x3b, 0xac, 0x03, 0x1c, 0xae, 0x7f, 0x60,
        /* pk appended */
        0xd7, 0x5a, 0x98, 0x01, 0x82, 0xb1, 0x0a, 0xb7,
        0xd5, 0x4b, 0xfe, 0xd3, 0xc9, 0x64, 0x07, 0x3a,
        0x0e, 0xe1, 0x72, 0xf3, 0xda, 0xa3, 0xf4, 0xa1,
        0x84, 0x46, 0xb0, 0xb8, 0xd1, 0x83, 0xf8, 0xe3
    };
    unsigned char pk[32] = {
        0xd7, 0x5a, 0x98, 0x01, 0x82, 0xb1, 0x0a, 0xb7,
        0xd5, 0x4b, 0xfe, 0xd3, 0xc9, 0x64, 0x07, 0x3a,
        0x0e, 0xe1, 0x72, 0xf3, 0xda, 0xa3, 0xf4, 0xa1,
        0x84, 0x46, 0xb0, 0xb8, 0xd1, 0x83, 0xf8, 0xe3
    };
    unsigned char msg[3] = {0x48, 0x65, 0x6c}; /* "Hel" */
    unsigned char sm[128];
    unsigned long long smlen;
    unsigned char m2[128];
    unsigned long long m2len;
    int ret;

    /* Sign */
    crypto_sign(sm, &smlen, msg, 3, sk);
    phex("sig", sm, 64);
    printf("smlen=%llu\n", smlen);

    /* Verify the signature we just produced */
    ret = crypto_sign_open(m2, &m2len, sm, smlen, pk);
    printf("verify=%d\n", ret);
    printf("mlen=%llu\n", m2len);
}

static void test_secretbox(void) {
    unsigned char key[32], nonce[24], m[96], c[96], m2[96];
    int i, r;
    memset(key, 0xab, 32);
    memset(nonce, 0xcd, 24);
    memset(m, 0, 32); /* zero padding */
    for (i = 32; i < 96; i++) m[i] = (unsigned char)(i * 3 + 7);

    r = crypto_secretbox(c, m, 96, nonce, key);
    printf("sb_enc=%d\n", r);
    phex("sb_ct", c + 16, 80);

    r = crypto_secretbox_open(m2, c, 96, nonce, key);
    printf("sb_dec=%d\n", r);
}

static void test_box(void) {
    unsigned char sk1[32], pk1[32], sk2[32], pk2[32];
    unsigned char nonce[24], m[64], c[64], m2[64];
    int r;

    memset(sk1, 0x11, 32);
    memset(sk2, 0x22, 32);
    crypto_scalarmult_base(pk1, sk1);
    crypto_scalarmult_base(pk2, sk2);
    phex("pk1", pk1, 32);
    phex("pk2", pk2, 32);

    memset(nonce, 0xef, 24);
    memset(m, 0, 32); /* zero padding */
    memcpy(m + 32, "Hello NaCl test!", 16);

    r = crypto_box(c, m, 48, nonce, pk2, sk1);
    printf("box_enc=%d\n", r);
    phex("box_ct", c + 16, 32);

    r = crypto_box_open(m2, c, 48, nonce, pk1, sk2);
    printf("box_dec=%d\n", r);
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <test>\n", argv[0]);
        fprintf(stderr, "Tests: hash salsa20 poly1305 curve25519 ed25519 secretbox box all\n");
        return 1;
    }

    if (strcmp(argv[1], "hash") == 0 || strcmp(argv[1], "all") == 0) test_hash();
    if (strcmp(argv[1], "salsa20") == 0 || strcmp(argv[1], "all") == 0) test_salsa20();
    if (strcmp(argv[1], "poly1305") == 0 || strcmp(argv[1], "all") == 0) test_poly1305();
    if (strcmp(argv[1], "curve25519") == 0 || strcmp(argv[1], "all") == 0) test_curve25519();
    if (strcmp(argv[1], "ed25519") == 0 || strcmp(argv[1], "all") == 0) test_ed25519();
    if (strcmp(argv[1], "secretbox") == 0 || strcmp(argv[1], "all") == 0) test_secretbox();
    if (strcmp(argv[1], "box") == 0 || strcmp(argv[1], "all") == 0) test_box();

    return 0;
}
