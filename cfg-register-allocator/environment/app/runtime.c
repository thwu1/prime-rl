
/*
 * C runtime for register-allocated x86-64 programs.
 * Provides main() which calls the assembly entry point _program_entry,
 * and read_int() which reads a long integer from stdin.
 *
 * Compile with:  gcc -o prog prog.s runtime.c -no-pie
 */

#include <stdio.h>

extern long _program_entry(void);

long read_int(void) {
    long val;
    if (scanf("%ld", &val) != 1)
        return 0;
    return val;
}

int main(void) {
    long result = _program_entry();
    printf("%ld\n", result);
    return 0;
}
