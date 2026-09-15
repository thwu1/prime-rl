/* case2.c - Type-punning through incompatible pointer types */
#include <stdio.h>
#include <stdint.h>

__attribute__((noinline))
int alias_test(int *ip, float *fp) {
    *ip = 42;
    *fp = 0.0f;
    return *ip;
}

int main(void) {
    int val;
    printf("%d\n", alias_test(&val, (float *)&val));
    return 0;
}
