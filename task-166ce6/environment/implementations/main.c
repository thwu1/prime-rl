/*
 * CLI wrapper for Poly1305 MAC implementations.
 * Usage: ./[alpha|beta|gamma] <r_hex_32> <s_hex_32> <msg_hex>
 * Outputs: 32-char lowercase hex tag
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

extern void poly1305_mac(const uint8_t *msg, size_t msg_len,
                         const uint8_t *key_r, const uint8_t *key_s,
                         uint8_t *tag_out);

static int hex_char_val(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static int hex_to_bytes(const char *hex, uint8_t *out, size_t max_len) {
    size_t hex_len = strlen(hex);
    if (hex_len % 2 != 0) return -1;
    size_t byte_len = hex_len / 2;
    if (byte_len > max_len) return -1;
    for (size_t i = 0; i < byte_len; i++) {
        int hi = hex_char_val(hex[2 * i]);
        int lo = hex_char_val(hex[2 * i + 1]);
        if (hi < 0 || lo < 0) return -1;
        out[i] = (uint8_t)((hi << 4) | lo);
    }
    return (int)byte_len;
}

int main(int argc, char *argv[]) {
    if (argc != 4) {
        fprintf(stderr, "Usage: %s <r_hex_32chars> <s_hex_32chars> <message_hex>\n", argv[0]);
        return 1;
    }

    uint8_t r[16], s[16];
    uint8_t msg[8192];

    if (hex_to_bytes(argv[1], r, 16) != 16) {
        fprintf(stderr, "Error: r must be exactly 32 hex chars (16 bytes)\n");
        return 1;
    }
    if (hex_to_bytes(argv[2], s, 16) != 16) {
        fprintf(stderr, "Error: s must be exactly 32 hex chars (16 bytes)\n");
        return 1;
    }
    int msg_len = hex_to_bytes(argv[3], msg, sizeof(msg));
    if (msg_len < 0) {
        fprintf(stderr, "Error: invalid message hex string\n");
        return 1;
    }

    uint8_t tag[16];
    poly1305_mac(msg, (size_t)msg_len, r, s, tag);

    for (int i = 0; i < 16; i++) {
        printf("%02x", tag[i]);
    }
    printf("\n");

    return 0;
}
