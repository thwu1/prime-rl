#include <stdio.h>

__attribute__((noinline))
int safe_add_check(unsigned int a, unsigned int b) {
    unsigned int sum = a + b;
    if (sum < a) return -1;
    return (int)sum;
}

int main() {
    printf("%d\n", safe_add_check(3000000000u, 2000000000u));
    return 0;
}
