#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "ed25519.h"


static int hex_to_bytes(const char *hex, uint8_t *out, size_t out_len) {
    size_t hex_len = strlen(hex);
    if (hex_len != out_len * 2) return -1;
    for (size_t i = 0; i < out_len; i++) {
        unsigned int byte;
        if (sscanf(hex + 2 * i, "%02x", &byte) != 1) return -1;
        out[i] = (uint8_t)byte;
    }
    return 0;
}

static void bytes_to_hex(const uint8_t *bytes, size_t len, char *out) {
    for (size_t i = 0; i < len; i++) {
        sprintf(out + 2 * i, "%02x", bytes[i]);
    }
    out[len * 2] = '\0';
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <keygen|sign|verify> ...\n", argv[0]);
        return 1;
    }

    if (strcmp(argv[1], "keygen") == 0) {
        if (argc != 3) {
            fprintf(stderr, "Usage: %s keygen <hex_secret_32bytes>\n", argv[0]);
            return 1;
        }
        uint8_t secret[32], pubkey[32];
        if (hex_to_bytes(argv[2], secret, 32) != 0) {
            fprintf(stderr, "Invalid secret key hex (expected 64 hex chars)\n");
            return 1;
        }
        ed25519_derive_pubkey(secret, pubkey);
        char hex[65];
        bytes_to_hex(pubkey, 32, hex);
        printf("%s\n", hex);

    } else if (strcmp(argv[1], "sign") == 0) {
        if (argc != 4) {
            fprintf(stderr, "Usage: %s sign <hex_secret> <hex_message>\n", argv[0]);
            return 1;
        }
        uint8_t secret[32];
        if (hex_to_bytes(argv[2], secret, 32) != 0) {
            fprintf(stderr, "Invalid secret key hex\n");
            return 1;
        }
        size_t msg_hex_len = strlen(argv[3]);
        if (msg_hex_len % 2 != 0) {
            fprintf(stderr, "Message hex must have even length\n");
            return 1;
        }
        size_t msg_len = msg_hex_len / 2;
        uint8_t *msg = NULL;
        if (msg_len > 0) {
            msg = malloc(msg_len);
            if (!msg) { fprintf(stderr, "malloc failed\n"); return 1; }
            if (hex_to_bytes(argv[3], msg, msg_len) != 0) {
                fprintf(stderr, "Invalid message hex\n");
                free(msg);
                return 1;
            }
        }
        uint8_t signature[64];
        ed25519_sign(secret, msg, msg_len, signature);
        char hex[129];
        bytes_to_hex(signature, 64, hex);
        printf("%s\n", hex);
        free(msg);

    } else if (strcmp(argv[1], "verify") == 0) {
        if (argc != 5) {
            fprintf(stderr, "Usage: %s verify <hex_pubkey> <hex_message> <hex_signature>\n", argv[0]);
            return 1;
        }
        uint8_t pubkey[32];
        if (hex_to_bytes(argv[2], pubkey, 32) != 0) {
            fprintf(stderr, "Invalid public key hex\n");
            return 1;
        }
        size_t msg_hex_len = strlen(argv[3]);
        if (msg_hex_len % 2 != 0) {
            fprintf(stderr, "Message hex must have even length\n");
            return 1;
        }
        size_t msg_len = msg_hex_len / 2;
        uint8_t *msg = NULL;
        if (msg_len > 0) {
            msg = malloc(msg_len);
            if (!msg) { fprintf(stderr, "malloc failed\n"); return 1; }
            if (hex_to_bytes(argv[3], msg, msg_len) != 0) {
                fprintf(stderr, "Invalid message hex\n");
                free(msg);
                return 1;
            }
        }
        uint8_t signature[64];
        if (hex_to_bytes(argv[4], signature, 64) != 0) {
            fprintf(stderr, "Invalid signature hex (expected 128 hex chars)\n");
            free(msg);
            return 1;
        }
        int valid = ed25519_verify(pubkey, msg, msg_len, signature);
        printf("%s\n", valid ? "VALID" : "INVALID");
        free(msg);

    } else {
        fprintf(stderr, "Unknown command: %s\n", argv[1]);
        return 1;
    }

    return 0;
}
