/*
 * C runtime for compiled x86-64 programs.
 * Provides print_int() for output and main() as the process entry point.
 *
 */

#include <stdio.h>

extern long compiler_main(void);

void print_int(long x) {
    printf("%ld\n", x);
}

long read_int(void) {
    long x = 0;
    if (scanf("%ld", &x) != 1) x = 0;
    return x;
}

int main(void) {
    long result = compiler_main();
    printf("RETVAL:%ld\n", result);
    return 0;
}
