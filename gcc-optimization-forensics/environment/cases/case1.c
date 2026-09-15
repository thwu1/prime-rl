/* case1.c - Fibonacci sequence (well-defined, no UB) */
#include <stdio.h>

__attribute__((noinline))
int fibonacci(int n) {
    int a = 0, b = 1;
    for (int i = 0; i < n; i++) {
        int tmp = a + b;
        a = b;
        b = tmp;
    }
    return a;
}

int main(void) {
    printf("%d\n", fibonacci(20));
    return 0;
}
