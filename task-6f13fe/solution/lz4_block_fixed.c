/*
 * LZ4 Block Format Compressor/Decompressor — FIXED VERSION
 *
 * Implements compression and decompression of raw LZ4 blocks
 * according to the LZ4 Block Format Specification (Yann Collet).
 *
 * Fixes applied:
 *   1. Match finder: memcmp uses MINMATCH (4) bytes, not 3
 *   2. Compressor offset: little-endian (low byte first)
 *   3. Compressor match length: ml_code = match_len - MINMATCH
 *   4. Decompressor offset: little-endian (low byte first)
 *   5. Decompressor match length: adds MINMATCH to decoded value
 *   6. Decompressor match copy: byte-by-byte for overlapping matches
 */

#include "lz4_block.h"
#include <string.h>
#include <stdlib.h>

/* ---- Format constants ---- */
#define MINMATCH       4     /* Minimum match length per spec */
#define LASTLITERALS   5     /* Last 5 bytes must be literals */
#define MFLIMIT       12     /* Minimum bytes needed for match search */
#define MAX_DISTANCE  65535  /* Maximum backward offset */

/* ---- Hash table parameters ---- */
#define HASH_LOG      14
#define HASH_SIZE     (1 << HASH_LOG)

/* Compute hash of 4 bytes at pointer p */
static uint32_t lz4_hash4(const uint8_t* p) {
    uint32_t val;
    memcpy(&val, p, sizeof(val));
    return (val * 2654435761U) >> (32 - HASH_LOG);
}

int lz4_compress_bound(int input_size) {
    if (input_size < 0) return 0;
    return input_size + (input_size / 255) + 16;
}

/*
 * Write variable-length continuation bytes for lengths >= 15.
 * 'remaining' is (total_length - 15), which has already been
 * signaled by placing 15 in the token nibble.
 * Returns number of bytes written to dst.
 */
static int write_var_length(uint8_t* dst, int remaining) {
    int n = 0;
    while (remaining >= 255) {
        dst[n++] = 255;
        remaining -= 255;
    }
    dst[n++] = (uint8_t)remaining;
    return n;
}


/* ================================================================
 *  COMPRESSOR
 * ================================================================ */

int lz4_block_compress(const uint8_t* src, uint8_t* dst,
                       int src_size, int dst_capacity) {
    /* Handle empty input */
    if (src_size <= 0) {
        if (dst_capacity < 1) return 0;
        dst[0] = 0;  /* Token: 0 literals, no match (end of block) */
        return 1;
    }

    const uint8_t* ip = src;            /* Current input position */
    const uint8_t* const iend = src + src_size;
    const uint8_t* const mflimit = iend - MFLIMIT;
    const uint8_t* const matchlimit = iend - LASTLITERALS;
    const uint8_t* anchor = src;        /* Start of current literal run */

    uint8_t* op = dst;                  /* Current output position */
    uint8_t* const oend = dst + dst_capacity;

    /* Hash table: stores positions (offsets from src) */
    uint32_t htable[HASH_SIZE];
    memset(htable, 0, sizeof(htable));

    /* Input too small to compress — emit as literals */
    if (src_size < MFLIMIT + 1) goto _last_literals;

    /* Hash first position */
    htable[lz4_hash4(ip)] = 0;
    ip++;

    /* Main compression loop */
    for (;;) {
        const uint8_t* ref;

        /* ---- Find a match using accelerated skip-search ---- */
        {
            int step = 1;
            int search_count = 0;
            const uint8_t* fwd = ip;

            do {
                ip = fwd;
                fwd += step;
                step = (search_count++ >> 5) + 1;

                if (fwd > mflimit) goto _last_literals;

                uint32_t h = lz4_hash4(ip);
                uint32_t ref_idx = htable[h];
                htable[h] = (uint32_t)(ip - src);
                ref = src + ref_idx;

                /* FIX 1: Compare MINMATCH (4) bytes, not 3 */
            } while ((ip - ref) > MAX_DISTANCE
                     || ref >= ip
                     || memcmp(ref, ip, MINMATCH) != 0);
        }

        /* Extend match backwards (catch-up) */
        while (ip > anchor && ref > src && ip[-1] == ref[-1]) {
            ip--;
            ref--;
        }

        /* ---- Encode sequence: literals + match ---- */
        {
            int lit_len = (int)(ip - anchor);

            /* Forward match extension */
            const uint8_t* mp = ref + MINMATCH;
            const uint8_t* cp = ip + MINMATCH;
            while (cp < matchlimit && *mp == *cp) {
                mp++;
                cp++;
            }
            int match_len = (int)(cp - ip);  /* Total match length */

            /* FIX 3: ml_code = match_len - MINMATCH (not match_len) */
            int ml_code = match_len - MINMATCH;

            /* Conservative output space check */
            int worst_case = 1
                + (lit_len >= 15 ? 1 + (lit_len - 15 + 254) / 255 : 0)
                + lit_len + 2
                + (ml_code >= 15 ? 1 + (ml_code - 15 + 254) / 255 : 0);
            if (op + worst_case > oend) return 0;

            /* Token byte */
            uint8_t* token = op++;

            /* Encode literal length in token high nibble + continuation */
            if (lit_len >= 15) {
                *token = 0xF0;
                op += write_var_length(op, lit_len - 15);
            } else {
                *token = (uint8_t)(lit_len << 4);
            }

            /* Copy literal bytes */
            if (lit_len > 0) {
                memcpy(op, anchor, lit_len);
                op += lit_len;
            }

            /* FIX 2: Offset in little-endian (low byte first, high byte second) */
            {
                uint16_t offset = (uint16_t)(ip - ref);
                *op++ = (uint8_t)(offset & 0xFF);
                *op++ = (uint8_t)((offset >> 8) & 0xFF);
            }

            /* Encode match length in token low nibble + continuation */
            if (ml_code >= 15) {
                *token |= 0x0F;
                op += write_var_length(op, ml_code - 15);
            } else {
                *token |= (uint8_t)ml_code;
            }

            /* Advance past the match */
            ip += match_len;
            anchor = ip;
        }

        /* End-of-input check */
        if (ip > mflimit) goto _last_literals;

        /* Update hash table for recent positions */
        htable[lz4_hash4(ip - 2)] = (uint32_t)((ip - 2) - src);

        /* Hash current position for next iteration */
        {
            uint32_t h = lz4_hash4(ip);
            htable[h] = (uint32_t)(ip - src);
        }

        ip++;
    }

_last_literals:
    /* Encode remaining input bytes as literals (no match) */
    {
        int last_run = (int)(iend - anchor);
        int need = 1 + (last_run >= 15 ? 1 + (last_run - 15 + 254) / 255 : 0)
                 + last_run;
        if (op + need > oend) return 0;

        if (last_run >= 15) {
            *op++ = 0xF0;
            op += write_var_length(op, last_run - 15);
        } else {
            *op++ = (uint8_t)(last_run << 4);
        }

        memcpy(op, anchor, last_run);
        op += last_run;
    }

    return (int)(op - dst);
}


/* ================================================================
 *  DECOMPRESSOR
 * ================================================================ */

int lz4_block_decompress(const uint8_t* src, uint8_t* dst,
                         int src_size, int dst_capacity) {
    if (src_size <= 0 || dst_capacity < 0) return 0;

    const uint8_t* ip = src;
    const uint8_t* const iend = src + src_size;

    uint8_t* op = dst;
    uint8_t* const oend = dst + dst_capacity;

    while (ip < iend) {
        /* Read token byte */
        uint8_t token = *ip++;

        /* ---- Decode literal length ---- */
        int lit_len = (token >> 4) & 0x0F;
        if (lit_len == 15) {
            int s;
            do {
                if (ip >= iend) return -1;
                s = *ip++;
                lit_len += s;
            } while (s == 255);
        }

        /* Copy literals from compressed stream to output */
        if (lit_len > 0) {
            if (ip + lit_len > iend) return -2;
            if (op + lit_len > oend) return -3;
            memcpy(op, ip, lit_len);
            ip += lit_len;
            op += lit_len;
        }

        /* Check for end of block (last sequence has only literals) */
        if (ip >= iend) break;

        /* ---- FIX 4: Decode offset in little-endian ---- */
        if (ip + 2 > iend) return -4;
        uint16_t offset = (uint16_t)ip[0] | ((uint16_t)ip[1] << 8);
        ip += 2;

        if (offset == 0) return -5;  /* Invalid offset per spec */

        /* ---- FIX 5: Decode match length, adding MINMATCH ---- */
        int match_len = (token & 0x0F) + MINMATCH;
        if ((token & 0x0F) == 15) {
            int s;
            do {
                if (ip >= iend) return -6;
                s = *ip++;
                match_len += s;
            } while (s == 255);
        }

        /* Validate match source position */
        uint8_t* match_pos = op - offset;
        if (match_pos < dst) return -7;    /* Offset before start of buffer */
        if (op + match_len > oend) return -8;

        /* FIX 6: Copy match data byte-by-byte to handle overlap correctly.
         * When offset < match_len, memcpy behavior is undefined because
         * source and destination overlap. Byte-by-byte copy ensures that
         * each byte is written before being read in subsequent iterations,
         * which is required for patterns like offset=1 (run-length encoding). */
        {
            int i;
            for (i = 0; i < match_len; i++) {
                op[i] = match_pos[i];
            }
        }
        op += match_len;
    }

    return (int)(op - dst);
}
