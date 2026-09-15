#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

/*
 * MAC Engine - Polynomial MAC over GF(2^64) with TEA block cipher.
 * Provides MAC verification for the authenticated protocol.
 */

void tea_encrypt(uint8_t *v, const uint8_t *key) {
    uint32_t v0 = ((uint32_t)v[0]<<24)|((uint32_t)v[1]<<16)|((uint32_t)v[2]<<8)|v[3];
    uint32_t v1 = ((uint32_t)v[4]<<24)|((uint32_t)v[5]<<16)|((uint32_t)v[6]<<8)|v[7];
    uint32_t k0 = ((uint32_t)key[0]<<24)|((uint32_t)key[1]<<16)|((uint32_t)key[2]<<8)|key[3];
    uint32_t k1 = ((uint32_t)key[4]<<24)|((uint32_t)key[5]<<16)|((uint32_t)key[6]<<8)|key[7];
    uint32_t k2 = ((uint32_t)key[8]<<24)|((uint32_t)key[9]<<16)|((uint32_t)key[10]<<8)|key[11];
    uint32_t k3 = ((uint32_t)key[12]<<24)|((uint32_t)key[13]<<16)|((uint32_t)key[14]<<8)|key[15];
    uint32_t delta = 0x9E3779B9;
    uint32_t sum = 0;
    int i;
    for (i = 0; i < 32; i++) {
        sum += delta;
        v0 += ((v1<<4)+k0) ^ (v1+sum) ^ ((v1>>5)+k1);
        v1 += ((v0<<4)+k2) ^ (v0+sum) ^ ((v0>>5)+k3);
    }
    v[0]=(uint8_t)(v0>>24); v[1]=(uint8_t)(v0>>16);
    v[2]=(uint8_t)(v0>>8);  v[3]=(uint8_t)v0;
    v[4]=(uint8_t)(v1>>24); v[5]=(uint8_t)(v1>>16);
    v[6]=(uint8_t)(v1>>8);  v[7]=(uint8_t)v1;
}

/* GF(2^64) multiplication with reduction polynomial */
uint64_t gf64_multiply(uint64_t a, uint64_t b) {
    uint64_t result = 0;
    uint64_t reduction = 0x1BULL;
    int i;
    for (i = 0; i < 64; i++) {
        if (b & 1ULL)
            result ^= a;
        b >>= 1;
        uint64_t carry = a >> 63;
        a <<= 1;
        if (carry)
            a ^= reduction;
    }
    return result;
}

uint64_t compute_mac_tag(const uint8_t *ct, size_t ct_len,
                         uint64_t h, uint64_t s) {
    uint64_t acc = 0;
    size_t off;
    for (off = 0; off < ct_len; off += 8) {
        uint64_t block = 0;
        int j;
        for (j = 0; j < 8 && off + (size_t)j < ct_len; j++)
            block = (block << 8) | ct[off + j];
        acc = gf64_multiply(acc ^ block, h);
    }
    return acc ^ s;
}

void derive_mac_keys(const uint8_t *nonce, const uint8_t *key,
                     uint64_t *h, uint64_t *s) {
    uint8_t h_buf[8], s_buf[8];
    int i;
    memcpy(h_buf, nonce, 8);
    tea_encrypt(h_buf, key);
    *h = 0;
    for (i = 0; i < 8; i++) *h = (*h << 8) | h_buf[i];
    for (i = 0; i < 8; i++) s_buf[i] = nonce[i] ^ 0xFF;
    tea_encrypt(s_buf, key);
    *s = 0;
    for (i = 0; i < 8; i++) *s = (*s << 8) | s_buf[i];
}

int hex_to_bytes(const char *hex, uint8_t *out, size_t max_len) {
    size_t hlen = strlen(hex);
    size_t i;
    if (hlen % 2 != 0 || hlen / 2 > max_len) return -1;
    for (i = 0; i < hlen / 2; i++) {
        unsigned int val;
        if (sscanf(hex + 2*i, "%02x", &val) != 1) return -1;
        out[i] = (uint8_t)val;
    }
    return (int)(hlen / 2);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage:\n");
        fprintf(stderr, "  %s info\n", argv[0]);
        fprintf(stderr, "  %s verify <ct_hex> <nonce_hex> <tag_hex> <key_hex>\n", argv[0]);
        return 1;
    }
    if (strcmp(argv[1], "info") == 0) {
        printf("MAC Engine v2.1 - Polynomial MAC Authentication\n");
        printf("Block size: 8 bytes (64 bits)\n");
        printf("Tag size: 8 bytes (64 bits)\n");
        printf("Block cipher: TEA (32 rounds)\n");
        printf("Construction: Polynomial evaluation with one-time mask\n");
        return 0;
    }
    if (strcmp(argv[1], "verify") == 0) {
        if (argc != 6) {
            fprintf(stderr, "verify: <ct_hex> <nonce_hex> <tag_hex> <key_hex>\n");
            return 1;
        }
        uint8_t ct[1024], nonce[8], key[16];
        int ct_len = hex_to_bytes(argv[2], ct, sizeof(ct));
        if (ct_len < 0) { fprintf(stderr, "Invalid ciphertext hex\n"); return 1; }
        if (hex_to_bytes(argv[3], nonce, 8) != 8) { fprintf(stderr, "Invalid nonce hex\n"); return 1; }
        if (hex_to_bytes(argv[5], key, 16) != 16) { fprintf(stderr, "Invalid key hex\n"); return 1; }
        uint64_t provided_tag;
        if (sscanf(argv[4], "%016lx", &provided_tag) != 1) {
            fprintf(stderr, "Invalid tag hex\n");
            return 1;
        }
        uint64_t h, s;
        derive_mac_keys(nonce, key, &h, &s);
        uint64_t computed = compute_mac_tag(ct, (size_t)ct_len, h, s);
        if (computed == provided_tag) {
            printf("VALID\n");
            return 0;
        } else {
            printf("INVALID (expected %016lx)\n", computed);
            return 1;
        }
    }
    fprintf(stderr, "Unknown command: %s\n", argv[1]);
    return 1;
}
