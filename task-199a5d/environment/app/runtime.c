/*
 * C runtime for the x86-64 backend.
 *
 * Provides print_int (called from generated assembly) and main
 * (which calls the generated program_entry symbol).
 */

#include <stdio.h>
#include <stdlib.h>

extern void program_entry(void);

void print_int(long val) {
    printf("%ld\n", val);
}

int main(void) {
    program_entry();
    return 0;
}
