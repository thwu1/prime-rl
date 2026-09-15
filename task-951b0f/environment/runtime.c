/*
 * Runtime support for the pseudo-x86 compiler.
 * Provides read_int and print_int functions that the generated
 * assembly calls for I/O.
 *
 */
#include <stdio.h>
#include <stdlib.h>

long read_int(void) {
    long val;
    if (scanf("%ld", &val) != 1) {
        fprintf(stderr, "read_int: invalid input\n");
        exit(1);
    }
    return val;
}

void print_int(long val) {
    printf("%ld\n", val);
}
