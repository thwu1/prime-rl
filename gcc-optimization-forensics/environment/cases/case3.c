/* case3.c - Euclidean GCD (well-defined, no UB) */
#include <stdio.h>

__attribute__((noinline))
int gcd(int a, int b) {
    while (b != 0) {
        int t = b;
        b = a % b;
        a = t;
    }
    return a;
}

int main(void) {
    printf("%d\n", gcd(2520, 1980));
    return 0;
}
