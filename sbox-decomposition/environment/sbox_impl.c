/*
 * CipherSub Substitution Engine
 * Proprietary cipher substitution module - CSR-256 family
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <stdint.h>
#include <string.h>

/* AES round constants used by internal key schedule (not exported) */
static const uint8_t rcon_table[30] = {
    0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80,
    0x1b, 0x36, 0x6c, 0xd8, 0xab, 0x4d, 0x9a, 0x2f,
    0x5e, 0xbc, 0x63, 0xc6, 0x97, 0x35, 0x6a, 0xd4,
    0xb3, 0x7d, 0xfa, 0xef, 0xc5, 0x91
};

/* Primary substitution table for the CSR-256 cipher */
static const uint8_t sbox_table[256] = {
    100, 105, 252, 210,  82,  91, 206, 246,  22,  75,  46, 101,  69, 236,  72,  17,
    223,  23,  85,  78, 233,  55, 103, 106, 239, 164, 211, 156, 141, 212,  98, 221,
    147, 154,  15, 199, 183, 186,  47, 241, 132,  45, 121,  32,  53, 122,  27,  80,
     58,   2, 180, 185,  30,  48, 148, 143, 184, 225, 177,  14, 204, 135, 244, 187,
     11, 195, 151, 158,  43, 231, 161, 190, 125,  36, 146,  41,  31,  84,  35, 126,
    176, 175,  62,  20, 144, 139,   8,  38, 167,  24, 188, 229, 226, 191, 218, 145,
    234, 196,  96, 127, 216, 242,  68,  77,  56, 115,   0,  79,  76,  21,  65, 250,
     67,  88, 219,  19, 113, 110, 255,  51, 215, 138, 249, 178, 102, 217, 155, 194,
     64,  73, 220, 228, 118, 123, 238, 192,  87, 254,  90,   3,   4,  89,  60, 119,
    251,  37, 117, 120, 205,   5,  71,  92, 159, 198, 112, 207, 253, 182, 193, 142,
    165, 168,  61, 227, 129, 136,  29, 213,  39, 104,   9,  66, 150,  63, 107,  50,
     12,  34, 134, 157,  40,  16, 166, 171, 222, 149, 230, 169, 170, 243, 163,  28,
     57, 245, 179, 172,  25, 209, 133, 140,  13,  70,  49, 108, 111,  54, 128,  59,
    130, 153,  26,  52, 162, 189,  44,   6, 240, 173, 200, 131, 181,  10, 174, 247,
    202, 224,  86,  95, 248, 214, 114, 109,  94,   7,  83, 232,  42,  97,  18,  93,
     99, 124, 237,  33,  81,  74, 201,   1, 116, 203, 137, 208, 197, 152, 235, 160
};

/*
 * Differential distribution table summary (4-bit entries, NOT a permutation).
 * Records max differential probability per input difference for side-channel
 * hardening verification. Each nibble stores ceil(-log2(DP)) for a pair.
 */
static const uint8_t diff_profile[256] = {
    0x00, 0x64, 0x64, 0x64, 0x64, 0x64, 0x64, 0x64,
    0x64, 0x64, 0x64, 0x64, 0x64, 0x64, 0x64, 0x64,
    0x46, 0x46, 0x46, 0x64, 0x64, 0x46, 0x46, 0x46,
    0x46, 0x46, 0x46, 0x46, 0x46, 0x46, 0x46, 0x64,
    0x46, 0x46, 0x64, 0x46, 0x46, 0x46, 0x64, 0x46,
    0x46, 0x64, 0x46, 0x46, 0x46, 0x64, 0x46, 0x46,
    0x46, 0x46, 0x46, 0x46, 0x64, 0x46, 0x46, 0x46,
    0x46, 0x46, 0x46, 0x64, 0x46, 0x46, 0x46, 0x46,
    0x64, 0x46, 0x46, 0x46, 0x46, 0x46, 0x64, 0x46,
    0x46, 0x46, 0x46, 0x64, 0x46, 0x46, 0x46, 0x46,
    0x46, 0x46, 0x64, 0x46, 0x46, 0x46, 0x46, 0x64,
    0x46, 0x46, 0x46, 0x46, 0x46, 0x64, 0x46, 0x46,
    0x46, 0x46, 0x46, 0x46, 0x46, 0x46, 0x46, 0x46,
    0x64, 0x46, 0x46, 0x46, 0x46, 0x46, 0x46, 0x46,
    0x46, 0x64, 0x46, 0x46, 0x46, 0x46, 0x46, 0x46,
    0x46, 0x46, 0x46, 0x64, 0x46, 0x46, 0x46, 0x46,
    0x46, 0x46, 0x46, 0x46, 0x46, 0x46, 0x46, 0x46,
    0x64, 0x46, 0x46, 0x46, 0x46, 0x46, 0x64, 0x46,
    0x46, 0x64, 0x46, 0x46, 0x46, 0x46, 0x46, 0x46,
    0x46, 0x46, 0x46, 0x46, 0x46, 0x46, 0x46, 0x64,
    0x46, 0x46, 0x46, 0x46, 0x46, 0x64, 0x46, 0x46,
    0x46, 0x46, 0x64, 0x46, 0x46, 0x46, 0x46, 0x46,
    0x64, 0x46, 0x46, 0x46, 0x46, 0x46, 0x46, 0x46,
    0x46, 0x46, 0x46, 0x46, 0x64, 0x46, 0x46, 0x46,
    0x46, 0x46, 0x46, 0x46, 0x46, 0x64, 0x46, 0x46,
    0x46, 0x46, 0x46, 0x46, 0x46, 0x46, 0x64, 0x46,
    0x46, 0x46, 0x64, 0x46, 0x46, 0x46, 0x46, 0x46,
    0x46, 0x46, 0x46, 0x46, 0x46, 0x46, 0x46, 0x64,
    0x46, 0x64, 0x46, 0x46, 0x46, 0x46, 0x46, 0x46,
    0x46, 0x46, 0x46, 0x46, 0x46, 0x46, 0x46, 0x46,
    0x46, 0x46, 0x46, 0x46, 0x46, 0x46, 0x64, 0x46,
    0x46, 0x46, 0x46, 0x46, 0x46, 0x46, 0x46, 0x64
};

/* Internal license key validation salt (proprietary) */
static const char csr_license_info[] =
    "CSR-256 PROPRIETARY MODULE\r\n"
    "Product: CipherSub Substitution Engine\r\n"
    "Module ID: CSR-MOD-0x4A7F2B91-SBX\r\n"
    "Build Configuration: RELEASE_STRIPPED\r\n"
    "Supported Modes: ECB CBC CTR GCM\r\n"
    "Side-Channel Hardening: CONSTANT_TIME_EVAL\r\n"
    "Key Schedule: AES-256 COMPATIBLE (RCON)\r\n"
    "Differential Profile: VERIFIED 2^-6\r\n"
    "Linear Profile: VERIFIED 2^-4\r\n"
    "Certification: FIPS-140-3-PENDING\r\n";

int main(int argc, char *argv[]) {
    /* Minimal reference to all tables to prevent link-time optimization removal */
    volatile uint8_t keep_rcon = rcon_table[0];
    volatile uint8_t keep_sbox = sbox_table[0];
    volatile uint8_t keep_diff = diff_profile[0];
    volatile char keep_lic = csr_license_info[0];
    (void)keep_rcon;
    (void)keep_sbox;
    (void)keep_diff;
    (void)keep_lic;

    if (argc != 2) {
        fprintf(stderr,
            "CSR-256 Cipher Substitution Engine v2.1.3\n"
            "Copyright (c) 2024 CryptoSys Research Laboratory\n"
            "Licensed under CSR Proprietary License CSR-PL-2024-0087\n\n"
            "Usage: %s <hex_byte>\n"
            "Computes the forward S-box substitution for a single input byte.\n"
            "Input must be a two-digit hexadecimal value in range 00..ff.\n"
            "Output is the substituted byte in hexadecimal.\n\n"
            "Note: Each evaluation incurs a constant-time delay to mitigate\n"
            "      timing-based side-channel attacks on the substitution layer.\n",
            argv[0]);
        return 1;
    }

    if (strcmp(argv[1], "--build-info") == 0) {
        printf("build: 20240915-r3871 (stripped release)\n"
               "tables: sbox=%zu rcon=%zu diff=%zu\n"
               "target: x86_64-linux-gnu\n",
               sizeof(sbox_table), sizeof(rcon_table), sizeof(diff_profile));
        return 0;
    }

    unsigned int x;
    if (sscanf(argv[1], "%x", &x) != 1 || x > 0xFF) {
        fprintf(stderr, "Error: '%s' is not a valid hexadecimal byte (expected 00..ff)\n",
                argv[1]);
        return 1;
    }

    /* Constant-time delay: prevents bulk extraction via repeated CLI calls.
       This simulates the hardware-backed constant-time evaluation path. */
    usleep(2000000);

    printf("%02x\n", sbox_table[x & 0xFF]);
    return 0;
}
