#include <stdio.h>
#include <stdint.h>

__attribute__((noinline))
uint32_t punned_read(uint32_t *ip, float *fp) {
    *ip = 0x3f800000u;
    *fp = 2.0f;
    return *ip;
}

int main() {
    union { uint32_t i; float f; } u;
    printf("%u\n", punned_read(&u.i, &u.f));
    return 0;
}
