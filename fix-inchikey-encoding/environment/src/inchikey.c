/*
 *
 * InChIKey generator implementation.
 *
 * Generates a 27-character InChIKey from an InChI string using the IUPAC
 * InChI base-26 encoding of SHA-256 hashes. The InChIKey format is:
 *   XXXXXXXXXXXXXX-YYYYYYYYFV-P   (14-10-1 characters)
 *
 * The SHA-256 implementation in sha256.c is correct. This file contains
 * the base-26 encoding, InChI layer parsing, and key assembly logic.
 */

#define _POSIX_C_SOURCE 200809L

#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include "sha256.h"
#include "inchikey.h"

/* ============================================================
 * Base-26 lookup tables
 * ============================================================ */

#define NUM_TRIPLETS 16384   /* 2^14 entries for 14-bit segments */
#define NUM_DOUBLETS 676     /* 26^2 entries for 9-bit segments (use first 512) */

static char triplets[NUM_TRIPLETS][4];  /* 3-char + NUL */
static char doublets[NUM_DOUBLETS][3];  /* 2-char + NUL */
static int  tables_ready = 0;

/*
 * Build the base-26 lookup tables used by the InChI key encoding.
 *
 * The triplet table maps 14-bit indices (0..16383) to 3-letter strings.
 * It is constructed by enumerating all 26^3 = 17576 possible three-letter
 * combinations in lexicographic order (AAA, AAB, AAC, ..., ZZZ), then
 * removing:
 *   - All combinations whose first letter is 'E' (676 entries)
 *   - All combinations in the lexicographic range TAA..TTV inclusive
 *     (516 entries)
 * This leaves exactly 2^14 = 16384 entries.
 *
 * The outer loop must iterate the first character position, the middle
 * loop the second, and the inner loop the third, producing the sequence:
 *   AAA, AAB, AAC, ..., AAZ, ABA, ABB, ..., ZZZ
 *
 * The doublet table maps 9-bit indices (0..511) to 2-letter strings from
 * the full set AA..ZZ (676 entries); only the first 512 are used.
 */
static void init_tables(void)
{
    if (tables_ready) return;

    /* --- doublet table (AA-ZZ) --- */
    int di = 0;
    for (int a = 0; a < 26; a++) {
        for (int b = 0; b < 26; b++) {
            doublets[di][0] = (char)('A' + a);
            doublets[di][1] = (char)('A' + b);
            doublets[di][2] = '\0';
            di++;
        }
    }

    /* --- triplet table ---
     * Three nested loops: i is the outermost, j is middle, k is inner.
     * Each variable maps to a character position in the 3-letter code.
     */
    int ti = 0;
    for (int i = 0; i < 26; i++) {
        for (int j = 0; j < 26; j++) {
            for (int k = 0; k < 26; k++) {
                char s[4];
                s[0] = (char)('A' + k);
                s[1] = (char)('A' + j);
                s[2] = (char)('A' + i);
                s[3] = '\0';

                /* Exclude triplets starting with 'E' */
                if (s[0] == 'E') continue;

                /* Exclude triplets in lexicographic range TAA..TTV */
                if (strcmp(s, "TAA") >= 0 && strcmp(s, "TTV") <= 0) continue;

                if (ti < NUM_TRIPLETS) {
                    memcpy(triplets[ti], s, 4);
                    ti++;
                }
            }
        }
    }

    tables_ready = 1;
}

/* ============================================================
 * Bit extraction and base-26 encoding
 * ============================================================ */

/*
 * Extract `count` bits starting at bit position `start` from a byte array.
 * Bit ordering within each byte: bit 0 is the LSB.
 * Byte ordering: byte 0 contains bits 0-7, byte 1 contains bits 8-15, etc.
 */
static uint32_t extract_bits(const uint8_t *data, int start, int count)
{
    uint32_t result = 0;
    for (int i = 0; i < count; i++) {
        int byte_idx = (start + i) / 8;
        int bit_idx  = (start + i) % 8;
        if (data[byte_idx] & (1u << bit_idx)) {
            result |= (1u << i);
        }
    }
    return result;
}

/*
 * Encode `total_bits` from a SHA-256 digest into a base-26 string.
 *
 * The digest bytes are treated as a little-endian integer. Bits are
 * consumed from the LSB: 14-bit segments are looked up in the triplet
 * table (yielding 3 characters each), and a final 9-bit segment is
 * looked up in the doublet table (yielding 2 characters).
 *
 * For 65 bits (major hash): 4 triplets + 1 doublet = 14 characters.
 * For 37 bits (minor hash): 2 triplets + 1 doublet =  8 characters.
 */
static void encode_base26(const uint8_t *digest, int total_bits, char *out)
{
    if (!tables_ready) init_tables();

    int nbytes = (total_bits + 7) / 8;
    uint8_t data[16];
    memset(data, 0, sizeof(data));

    /*
     * Copy the relevant digest bytes into the working buffer.
     * The InChI specification treats the hash as a little-endian
     * integer — byte 0 of the digest maps to the least-significant
     * position in the integer representation.
     */
    for (int i = 0; i < nbytes; i++) {
        data[i] = digest[nbytes - 1 - i];
    }

    int pos = 0;
    int bit_offset = 0;
    int bits_remaining = total_bits;

    while (bits_remaining > 0) {
        if (bits_remaining >= 10) {
            /* 14-bit segment -> triplet */
            uint32_t idx = extract_bits(data, bit_offset, 14);
            out[pos++] = triplets[idx][0];
            out[pos++] = triplets[idx][1];
            out[pos++] = triplets[idx][2];
            bit_offset += 14;
            bits_remaining -= 14;
        } else {
            /* 9-bit segment -> doublet */
            uint32_t idx = extract_bits(data, bit_offset, 9);
            out[pos++] = doublets[idx][0];
            out[pos++] = doublets[idx][1];
            bit_offset += 9;
            bits_remaining -= 9;
        }
    }
    out[pos] = '\0';
}

/* ============================================================
 * InChI string parsing and layer classification
 * ============================================================ */

/*
 * Classification of InChI layers for InChIKey hashing:
 *
 * Major hash (14 chars): formula, /c (connectivity), /h (hydrogen), /q (charge)
 * Minor hash (8 chars):  /b (double-bond stereo), /t (tetrahedral stereo),
 *                         /m (stereo mirror), /s (stereo type),
 *                         /i (isotope, with sub-layers)
 * Protonation char:       /p (proton balance)
 * Ignored for InChIKey:   /f (fixed-H), /r (reconnected), /o
 */

/* Return 1 if the layer prefix character belongs to the major hash */
static int is_major_layer(char prefix)
{
    return (prefix == 'c' || prefix == 'h' || prefix == 'q');
}

/* Return 1 if the layer prefix is the protonation layer */
static int is_protonation_layer(char prefix)
{
    return (prefix == 'p');
}

/* ============================================================
 * Main InChIKey generation
 * ============================================================ */

int generate_inchikey(const char *inchi, char *key_out)
{
    if (!inchi || !key_out) return -1;

    /* --- Step 1: Strip the InChI version prefix --- */
    if (strncmp(inchi, "InChI=", 6) != 0) return -1;

    /*
     * The InChI string starts with "InChI=1/" for non-standard
     * or "InChI=1S/" for standard InChI.
     * We need to detect the standard marker 'S' and set the flag
     * character accordingly ('S' for standard, 'N' for non-standard).
     */
    const char *content = inchi + 8;   /* skip past "InChI=1/" */
    char flag = 'N';

    /* --- Step 2: Split content into layers --- */
    char content_buf[4096];
    strncpy(content_buf, content, sizeof(content_buf) - 1);
    content_buf[sizeof(content_buf) - 1] = '\0';

    /* Major and minor hash input buffers */
    char major_buf[4096];
    char minor_buf[4096];
    int  protonation = 0;

    major_buf[0] = '\0';
    minor_buf[0] = '\0';

    /* Tokenize by '/' */
    char *layers[256];
    int nlayers = 0;
    {
        char *saveptr = NULL;
        char *tok = strtok_r(content_buf, "/", &saveptr);
        while (tok && nlayers < 256) {
            layers[nlayers++] = tok;
            tok = strtok_r(NULL, "/", &saveptr);
        }
    }

    if (nlayers == 0) return -1;

    /* First layer is always the molecular formula (part of major hash) */
    strcpy(major_buf, layers[0]);

    /* Classify subsequent layers */
    for (int i = 1; i < nlayers; i++) {
        char prefix = layers[i][0];

        if (is_protonation_layer(prefix)) {
            /* Parse /p value for the protonation character */
            protonation = atoi(layers[i] + 1);
        } else if (is_major_layer(prefix)) {
            /* Append to major hash input with '/' separator */
            strcat(major_buf, "/");
            strcat(major_buf, layers[i]);
        } else {
            /* Append to minor hash input with '/' separator */
            strcat(minor_buf, "/");
            strcat(minor_buf, layers[i]);
        }
    }

    /* --- Step 3: Compute SHA-256 hashes --- */
    uint8_t major_digest[32], minor_digest[32];

    sha256_hash((const uint8_t *)major_buf, strlen(major_buf), major_digest);

    /*
     * Per the InChI specification, the minor hash input is the minor layer
     * string concatenated with itself (doubled) before hashing, provided
     * the string is non-empty and shorter than 255 characters.
     */
    {
        size_t mlen = strlen(minor_buf);
        if (mlen > 0 && mlen < 255) {
            char doubled[8192];
            memcpy(doubled, minor_buf, mlen);
            memcpy(doubled + mlen, minor_buf, mlen);
            doubled[2 * mlen] = '\0';
            sha256_hash((const uint8_t *)doubled, 2 * mlen, minor_digest);
        } else {
            sha256_hash((const uint8_t *)minor_buf, mlen, minor_digest);
        }
    }

    /* --- Step 4: Base-26 encode the hashes --- */
    char major_key[16];  /* 14 chars + NUL */
    char minor_key[10];  /*  8 chars + NUL */

    encode_base26(major_digest, 65, major_key);  /* 65 bits -> 14 chars */
    encode_base26(minor_digest, 37, minor_key);  /* 37 bits ->  8 chars */

    /* --- Step 5: Assemble the InChIKey --- */
    char version = 'A';   /* InChI version 1 -> 'A' */

    /* Protonation character: 'N' + protonation_value
       N=0, O=+1, P=+2, ..., M=-1, L=-2, ... */
    char prot_char = (char)('N' + protonation);

    /* Format: XXXXXXXXXXXXXX-YYYYYYYYFV-P */
    sprintf(key_out, "%s-%s%c%c-%c",
            major_key, minor_key, flag, version, prot_char);

    return 0;
}
