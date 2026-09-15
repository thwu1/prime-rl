/*
 *
 * Key verification binary for XXTEA CPA challenge.
 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static unsigned char get_kb(int i) {
    /* Key bytes stored XORed with position-derived mask */
    static const unsigned char e[] = {
        0x60, 0x00, 0xB6, 0x01, 0xB3, 0x8D, 0x79, 0xEB,
        0x61, 0xA3, 0x46, 0x04, 0x71, 0x10, 0xB0, 0x19
    };
    return e[i] ^ (unsigned char)((i * 37 + 0x5A) & 0xFF);
}

static int hex2nibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

int main(int argc, char *argv[]) {
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <32-char-hex-key>\n", argv[0]);
        return 1;
    }
    const char *hex = argv[1];
    if (strlen(hex) != 32) {
        printf("INCORRECT\n");
        return 0;
    }
    unsigned char input[16];
    int i;
    for (i = 0; i < 16; i++) {
        int hi = hex2nibble(hex[i * 2]);
        int lo = hex2nibble(hex[i * 2 + 1]);
        if (hi < 0 || lo < 0) {
            printf("INCORRECT\n");
            return 0;
        }
        input[i] = (unsigned char)((hi << 4) | lo);
    }
    /* Constant-time comparison to avoid timing leaks on the verifier itself */
    int diff = 0;
    for (i = 0; i < 16; i++) {
        diff |= input[i] ^ get_kb(i);
    }
    if (diff == 0)
        printf("CORRECT\n");
    else
        printf("INCORRECT\n");
    return 0;
}
