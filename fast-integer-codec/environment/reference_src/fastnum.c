/*
 * fastnum.c — Fast integer serialization library (correct reference)
 */

#include "fastnum.h"
#include <string.h>

static const uint64_t kPow10[20] = {
    UINT64_C(1),
    UINT64_C(10),
    UINT64_C(100),
    UINT64_C(1000),
    UINT64_C(10000),
    UINT64_C(100000),
    UINT64_C(1000000),
    UINT64_C(10000000),
    UINT64_C(100000000),
    UINT64_C(1000000000),
    UINT64_C(10000000000),
    UINT64_C(100000000000),
    UINT64_C(1000000000000),
    UINT64_C(10000000000000),
    UINT64_C(100000000000000),
    UINT64_C(1000000000000000),
    UINT64_C(10000000000000000),
    UINT64_C(100000000000000000),
    UINT64_C(1000000000000000000),
    UINT64_C(10000000000000000000),
};

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

    while (n >= 100) {
        uint64_t q = n / 100;
        uint32_t r = (uint32_t)(n - q * 100);
        n = q;
        pos -= 2;
        buf[pos]     = kDigitPairs[r * 2];
        buf[pos + 1] = kDigitPairs[r * 2 + 1];
    }

    if (n >= 10) {
        buf[0] = kDigitPairs[n * 2];
        buf[1] = kDigitPairs[n * 2 + 1];
    } else {
        buf[0] = '0' + (char)n;
    }

    return ndigits;
}

int dec_to_uint64(const char *buf, int len, uint64_t *result) {
    if (len <= 0 || len > 20) return -2;

    if (len > 1 && buf[0] == '0') return -2;

    uint64_t val = 0;
    for (int i = 0; i < len; i++) {
        char c = buf[i];
        if (c < '0' || c > '9') return -2;
        uint8_t digit = (uint8_t)(c - '0');

        if (val > UINT64_C(1844674407370955161)) return -1;
        val *= 10;

        if (val > UINT64_MAX - digit) return -1;
        val += digit;
    }

    *result = val;
    return 0;
}

static inline char nibble_to_hex(uint8_t val) {
    return (char)(val + '0' + ((val > 9) * ('a' - '0' - 10)));
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

static inline int hex_to_nibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
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

int uint64_mul_overflow(uint64_t a, uint64_t b) {
    if (a == 0 || b == 0) return 0;
    return a > UINT64_MAX / b ? 1 : 0;
}
