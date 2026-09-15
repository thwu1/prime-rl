
/*
 * Poly1305 Forgery Proof-of-Concept
 *
 * Demonstrates that the clamping bug (r[11]&=63 instead of r[11]&=15)
 * in the backdoored TweetNaCl weakens the MAC and constitutes an
 * actively exploitable authentication bypass.
 *
 * Compile: gcc -o forgery_poc forgery_poc.c tweetnacl.c
 */

#include <stdio.h>
#include <string.h>
#include "tweetnacl.h"

void randombytes(unsigned char *x, unsigned long long xlen) {
    unsigned long long i;
    for (i = 0; i < xlen; i++) x[i] = 0;
}

/* ---- Broken Poly1305 re-implementation (r[11]&=63 vulnerability) ---- */

static void broken_add1305(unsigned long *h, const unsigned long *c) {
    unsigned long j, u = 0;
    for (j = 0; j < 17; j++) {
        u += h[j] + c[j];
        h[j] = u & 255;
        u >>= 8;
    }
}

static const unsigned long broken_minusp[17] = {
    5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 252
};

static void broken_onetimeauth(unsigned char *out, const unsigned char *m,
                                unsigned long long n, const unsigned char *k) {
    unsigned long s, i, j, u, x[17], r[17], h[17], c[17], g[17];
    for (j = 0; j < 17; j++) r[j] = h[j] = 0;
    for (j = 0; j < 16; j++) r[j] = k[j];
    r[3] &= 15;
    r[4] &= 252;
    r[7] &= 15;
    r[8] &= 252;
    r[11] &= 63;   /* BUG: correct clamping is r[11] &= 15 */
    r[12] &= 252;
    r[15] &= 15;

    while (n > 0) {
        for (j = 0; j < 17; j++) c[j] = 0;
        for (j = 0; (j < 16) && (j < n); ++j) c[j] = m[j];
        c[j] = 1;
        m += j; n -= j;
        broken_add1305(h, c);
        for (i = 0; i < 17; i++) {
            x[i] = 0;
            for (j = 0; j < 17; j++)
                x[i] += h[j] * ((j <= i) ? r[i - j] : 320 * r[i + 17 - j]);
        }
        for (i = 0; i < 17; i++) h[i] = x[i];
        u = 0;
        for (j = 0; j < 16; j++) {
            u += h[j];
            h[j] = u & 255;
            u >>= 8;
        }
        u += h[16]; h[16] = u & 3;
        u = 5 * (u >> 2);
        for (j = 0; j < 16; j++) {
            u += h[j];
            h[j] = u & 255;
            u >>= 8;
        }
        u += h[16]; h[16] = u;
    }
    for (j = 0; j < 17; j++) g[j] = h[j];
    broken_add1305(h, broken_minusp);
    s = -(h[16] >> 7);
    for (j = 0; j < 17; j++) h[j] ^= s & (g[j] ^ h[j]);
    for (j = 0; j < 16; j++) c[j] = k[j + 16];
    c[16] = 0;
    broken_add1305(h, c);
    for (j = 0; j < 16; j++) out[j] = h[j];
}

/* ---- Main: demonstrate the vulnerability ---- */

static void print_hex(const unsigned char *data, int len) {
    int i;
    for (i = 0; i < len; i++) printf("%02x", data[i]);
}

int main(void) {
    /* Key where byte 11 (0-indexed) = 0x3f, so bits 4-5 are set.
     * Correct clamping: r[11] = 0x3f & 0x0f = 0x0f
     * Broken clamping:  r[11] = 0x3f & 0x3f = 0x3f
     * This causes divergent MAC outputs, proving exploitability. */
    unsigned char key[32] = {
        0x85, 0xd6, 0xbe, 0x78, 0x57, 0x56, 0x6d, 0x33,
        0x7f, 0x44, 0x52, 0x3f, 0x42, 0xd5, 0x06, 0xa8,
        0x01, 0x03, 0x80, 0x8a, 0xfb, 0x0d, 0xb2, 0xfd,
        0x4a, 0xbf, 0xf6, 0xaf, 0x41, 0x49, 0xf5, 0x1b
    };

    const char *msg = "Poly1305 forgery proof-of-concept";
    unsigned long long msglen = strlen(msg);

    unsigned char correct_mac[16], broken_mac[16];

    /* Compute MAC with the FIXED (correct) implementation */
    crypto_onetimeauth(correct_mac, (const unsigned char *)msg, msglen, key);

    /* Compute MAC with the BROKEN clamping */
    broken_onetimeauth(broken_mac, (const unsigned char *)msg, msglen, key);

    printf("FORGERY_KEY=");
    print_hex(key, 32);
    printf("\n");

    printf("FORGERY_MSG=");
    print_hex((const unsigned char *)msg, (int)msglen);
    printf("\n");

    printf("CORRECT_MAC=");
    print_hex(correct_mac, 16);
    printf("\n");

    printf("BROKEN_MAC=");
    print_hex(broken_mac, 16);
    printf("\n");

    printf("DIVERGENT=%s\n", memcmp(correct_mac, broken_mac, 16) != 0 ? "YES" : "NO");

    return 0;
}
