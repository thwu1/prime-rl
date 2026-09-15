#include <stdio.h>

__attribute__((noinline))
unsigned int byte_swap(unsigned int x) {
    return ((x & 0xFFu) << 24) | ((x & 0xFF00u) << 8) |
           ((x & 0xFF0000u) >> 8) | ((x >> 24) & 0xFFu);
}

int main() {
    printf("%u\n", byte_swap(0x12345678u));
    return 0;
}
