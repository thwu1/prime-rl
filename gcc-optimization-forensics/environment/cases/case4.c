/* case4.c - Post-hoc signed overflow detection */
#include <stdio.h>
#include <limits.h>

__attribute__((noinline))
int detect_overflow(int a, int b) {
    int sum = a + b;
    if (a > 0 && b > 0 && sum < 0)
        return 1;
    return 0;
}

int main(void) {
    volatile int x = INT_MAX;
    volatile int y = 1;
    printf("%d\n", detect_overflow(x, y));
    return 0;
}
