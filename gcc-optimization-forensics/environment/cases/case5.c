/* case5.c - Popcount via Kernighan's method (well-defined, no UB) */
#include <stdio.h>

__attribute__((noinline))
int popcount(unsigned int x) {
    int count = 0;
    while (x) {
        count++;
        x &= x - 1;
    }
    return count;
}

int main(void) {
    printf("%d\n", popcount(0xCAFEBABEu));
    return 0;
}
