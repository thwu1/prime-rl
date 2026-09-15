/* SEAT Transform - native implementation */

#include <stdint.h>

static const uint64_t pool[] = {
    0xA5A5A5A5A5A5A5A5ULL,   /* 0 */
    0xBADCAFE0DEADBEEFULL,   /* 1 */
    0x1337FACE8BADF00DULL,   /* 2 */
    0xFEEDFACEDEADC0DEULL,   /* 3 */
    0x3C3C3C3C3C3C3C3CULL,   /* 4 */
    0xDEADBEEFCAFEBABEULL,   /* 5 */
    0x6969696969696969ULL    /* 6 */
};

static const uint64_t RED = 0x1BULL;

static uint64_t gf_mul(uint64_t a, uint64_t b) {
    uint64_t r = 0;
    int i;
    for (i = 0; i < 64; i++) {
        if ((b >> i) & 1)
            r ^= a;
        uint64_t c = (a >> 63) & 1;
        a <<= 1;
        if (c)
            a ^= RED;
    }
    return r;
}

uint64_t seat_transform(uint64_t x) {
    x ^= pool[5];
    x = gf_mul(x, pool[0]);
    x ^= pool[2];
    x = gf_mul(x, pool[4]);
    x ^= pool[3];
    x = gf_mul(x, pool[6]);
    x ^= pool[1];
    return x;
}
