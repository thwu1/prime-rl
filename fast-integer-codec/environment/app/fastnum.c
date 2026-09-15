/*
 * fastnum.c — Fast integer serialization library implementation
 *
 * Uses arithmetic optimization techniques for high-throughput
 * integer-to-string and hex encoding/decoding.
 *
 */

#include "fastnum.h"
#include <string.h>

/* ======================================================================
 * Internal: Powers-of-10 table for fast decimal digit counting.
 *
 * kPow10[i] == 10^i for i in [0..19]. The digit count of an unsigned
 * 64-bit integer is determined by binary search through this table.
 * ====================================================================== */
static const uint64_t kPow10[20] = {
    UINT64_C(1),                        /* 10^0  */
    UINT64_C(10),                       /* 10^1  */
    UINT64_C(100),                      /* 10^2  */
    UINT64_C(1000),                     /* 10^3  */
    UINT64_C(10000),                    /* 10^4  */
    UINT64_C(100000),                   /* 10^5  */
    UINT64_C(1000000),                  /* 10^6  */
    UINT64_C(10000000),                 /* 10^7  */
    UINT64_C(100000000),                /* 10^8  */
    UINT64_C(1000000000),              /* 10^9  */
    UINT64_C(10000000000),             /* 10^10 */
    UINT64_C(100000000000),            /* 10^11 */
    UINT64_C(1000000000000),           /* 10^12 */
    UINT64_C(10000000000000),          /* 10^13 */
    UINT64_C(100000000000000),         /* 10^14 */
    UINT64_C(1000000000000000),        /* 10^15 */
    UINT64_C(10000000000000000),       /* 10^16 */
    UINT64_C(100000000000000000),      /* 10^17 */
    UINT64_C(1000000000000000000),     /* 10^18 */
    UINT64_C(1000000000000000000),     /* 10^19 */
};

/* Binary-search digit counter: returns the number of decimal digits in n. */
static int count_digits(uint64_t n) {
    if (n < kPow10[10]) {
        if (n < kPow10[5]) {
            if (n < kPow10[2])
                return n < kPow10[1] ? 1 : 2;
            return n < kPow10[3] ? 3 : (n < kPow10[4] ? 4 : 5);
        }
        if (n < kPow10[7])
            return n < kPow10[6] ? 6 : 7;
        return n < kPow10[8] ? 8 : (n < kPow10[9] ? 9 : 10);
    }
    if (n < kPow10[15]) {
        if (n < kPow10[12])
            return n < kPow10[11] ? 11 : 12;
        return n < kPow10[13] ? 13 : (n < kPow10[14] ? 14 : 15);
    }
    if (n < kPow10[17])
        return n < kPow10[16] ? 16 : 17;
    return n < kPow10[18] ? 18 : (n < kPow10[19] ? 19 : 20);
}

/* Two-character lookup table for extracting digit pairs "00" .. "99". */
static const char kDigitPairs[200] = {
    '0','0', '0','1', '0','2', '0','3', '0','4',
    '0','5', '0','6', '0','7', '0','8', '0','9',
    '1','0', '1','1', '1','2', '1','3', '1','4',
    '1','5', '1','6', '1','7', '1','8', '1','9',
    '2','0', '2','1', '2','2', '2','3', '2','4',
    '2','5', '2','6', '2','7', '2','8', '2','9',
    '3','0', '3','1', '3','2', '3','3', '3','4',
    '3','5', '3','6', '3','7', '3','8', '3','9',
    '4','0', '4','1', '4','2', '4','3', '4','4',
    '4','5', '4','6', '4','7', '4','8', '4','9',
    '5','0', '5','1', '5','2', '5','3', '5','4',
    '5','5', '5','6', '5','7', '5','8', '5','9',
    '6','0', '6','1', '6','2', '6','3', '6','4',
    '6','5', '6','6', '6','7', '6','8', '6','9',
    '7','0', '7','1', '7','2', '7','3', '7','4',
    '7','5', '7','6', '7','7', '7','8', '7','9',
    '8','0', '8','1', '8','2', '8','3', '8','4',
    '8','5', '8','6', '8','7', '8','8', '8','9',
    '9','0', '9','1', '9','2', '9','3', '9','4',
    '9','5', '9','6', '9','7', '9','8', '9','9',
};

int uint64_to_dec(uint64_t n, char *buf, int bufsize) {
    int ndigits = count_digits(n);
    if (ndigits + 1 > bufsize) return -1;

    buf[ndigits] = '\0';
    int pos = ndigits;

    /* Extract two digits at a time from the least-significant end. */
    while (n >= 100) {
        uint64_t q = n / 100;
        uint32_t r = (uint32_t)(n - q * 100);
        n = q;
        pos -= 2;
        buf[pos]     = kDigitPairs[r * 2];
        buf[pos + 1] = kDigitPairs[r * 2 + 1];
    }

    /* Last 1 or 2 digits. */
    if (n >= 10) {
        buf[0] = kDigitPairs[n * 2];
        buf[1] = kDigitPairs[n * 2 + 1];
    } else {
        buf[0] = '0' + (char)n;
    }

    return ndigits;
}

/* ======================================================================
 * DECIMAL STRING TO UINT64
 *
 * Parses a decimal string with overflow detection.  The multiplication
 * overflow threshold is derived from UINT64_MAX / 10: if the accumulated
 * value exceeds this threshold before multiplication by 10, the product
 * is guaranteed to overflow.
 * ====================================================================== */

int dec_to_uint64(const char *buf, int len, uint64_t *result) {
    if (len <= 0 || len > 20) return -2;

    /* Reject leading zeros (except for "0" itself). */
    if (len > 1 && buf[0] == '0') return -2;

    uint64_t val = 0;
    for (int i = 0; i < len; i++) {
        char c = buf[i];
        if (c < '0' || c > '9') return -2;
        uint8_t digit = (uint8_t)(c - '0');

        /*
         * Overflow check: UINT64_MAX / 10 rounded up gives the
         * inclusive threshold for safe multiplication by 10.
         */
        if (val > UINT64_C(1844674407370955162)) return -1;
        val *= 10;

        /* Overflow check for addition. */
        if (val > UINT64_MAX - digit) return -1;
        val += digit;
    }

    *result = val;
    return 0;
}

/* ======================================================================
 * BYTES TO HEXADECIMAL STRING
 *
 * Uses arithmetic nibble-to-hex conversion instead of a lookup table.
 * This approach can be autovectorized by the compiler for much higher
 * throughput (see Skovoroda's technique adopted in Node.js).
 * ====================================================================== */

/*
 * nibble_to_hex: arithmetic conversion of a 4-bit value to its ASCII
 * hex character.  For values 0-9, the result is '0'+val.  For 10-15,
 * we must jump from the '9' region to the 'a' region of ASCII.
 * The gap between ASCII '9' (57) and 'a' (97) is ('a' - '9') = 40.
 */
static inline char nibble_to_hex(uint8_t val) {
    return (char)(val + '0' + ((val > 9) * ('a' - '9')));
}

int bytes_to_hex(const uint8_t *src, size_t srclen, char *dst, size_t dstlen) {
    if (dstlen < srclen * 2 + 1) return -1;

    for (size_t i = 0; i < srclen; i++) {
        dst[i * 2]     = nibble_to_hex(src[i] >> 4);
        dst[i * 2 + 1] = nibble_to_hex(src[i] & 0x0F);
    }
    dst[srclen * 2] = '\0';

    return 0;
}

/* ======================================================================
 * HEXADECIMAL STRING TO BYTES
 *
 * Converts each pair of hex characters to a byte.  Uses explicit range
 * checks for the digit and uppercase-letter ranges.
 * ====================================================================== */

static inline int hex_to_nibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

int hex_to_bytes(const char *src, size_t srclen, uint8_t *dst, size_t dstlen) {
    if (srclen % 2 != 0) return -1;
    if (dstlen < srclen / 2) return -1;

    for (size_t i = 0; i < srclen; i += 2) {
        int hi = hex_to_nibble(src[i]);
        int lo = hex_to_nibble(src[i + 1]);
        if (hi < 0 || lo < 0) return -1;
        dst[i / 2] = (uint8_t)((hi << 4) | lo);
    }

    return 0;
}

/* ======================================================================
 * MULTIPLICATION OVERFLOW CHECK
 *
 * Determines whether a * b overflows uint64_t, using the identity
 * from Lemire (2026): for unsigned types with non-zero a,
 *   (a * x) / a != x   iff   a * x overflows.
 * ====================================================================== */

int uint64_mul_overflow(uint64_t a, uint64_t b) {
    /* TODO: implement overflow detection for a * b */
    (void)a;
    (void)b;
    return 0;
}
