#include <stdio.h>
#include <stdlib.h>

void print_int(long x) {
    printf("%ld\n", x);
}

long read_int(void) {
    long x;
    if (scanf("%ld", &x) != 1) {
        fprintf(stderr, "read_int: invalid input\n");
        exit(1);
    }
    return x;
}
