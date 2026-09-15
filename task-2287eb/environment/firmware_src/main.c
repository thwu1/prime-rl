/*
 * Cortex-M4 firmware: PRNG + mixing hash computation
 * Outputs result via BKPT #255 syscall
 */
#include <stdint.h>

static uint32_t xs_state;

uint32_t __attribute__((noinline)) xorshift32(void) {
    uint32_t x = xs_state;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    xs_state = x;
    return x;
}

void __attribute__((noinline)) sipround(uint32_t v[4]) {
    v[0] += v[1];
    v[1] = ((v[1] << 5) | (v[1] >> 27)) ^ v[0];
    v[2] += v[3];
    v[3] = ((v[3] << 8) | (v[3] >> 24)) ^ v[2];
    v[0] = (v[0] << 16) | (v[0] >> 16);
    v[0] += v[3];
    v[2] += v[1];
    v[1] = ((v[1] << 13) | (v[1] >> 19)) ^ v[2];
    v[3] = ((v[3] << 7) | (v[3] >> 25)) ^ v[0];
    v[2] = (v[2] << 16) | (v[2] >> 16);
}

void __attribute__((noinline)) output_write(const void *data, uint32_t len) {
    register const void *r0 __asm__("r0") = data;
    register uint32_t r1 __asm__("r1") = len;
    __asm__ volatile("bkpt #255" : : "r"(r0), "r"(r1) : "memory");
}

int main(void) {
    xs_state = 0xDEADBEEF;

    uint32_t v[4];
    v[0] = 0x736f6d65;
    v[1] = 0x646f7261;
    v[2] = 0x6c796765;
    v[3] = 0x74656462;

    for (int i = 0; i < 32; i++) {
        uint32_t r = xorshift32();
        v[3] ^= r;
        sipround(v);
        sipround(v);
        v[0] ^= r;
    }

    v[2] ^= 0xFF;
    for (int i = 0; i < 4; i++) {
        sipround(v);
    }

    output_write(v, 16);

    __asm__ volatile("bkpt #0");
    while(1);

    return 0;
}
