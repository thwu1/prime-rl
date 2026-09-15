#include <stdio.h>
#include <limits.h>

__attribute__((noinline))
int check_abs(int x) {
    if (x < 0) x = -x;
    return x >= 0;
}

int main() {
    printf("%d\n", check_abs(INT_MIN));
    return 0;
}
