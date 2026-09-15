#include <stdio.h>
#include <limits.h>

__attribute__((noinline))
int check(int x) {
    return (x + 1) > x;
}

int main() {
    printf("%d\n", check(INT_MAX));
    return 0;
}
