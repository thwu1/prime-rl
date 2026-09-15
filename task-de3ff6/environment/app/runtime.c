/* C runtime for pseudo-x86 compiled programs.
 *
 *
 * Provides:
 *   - main(): calls program_entry() and prints its return value
 *   - print_int(long): prints an integer to stdout
 *
 * Compile: gcc -no-pie -o binary program.s runtime.c
 */

#include <stdio.h>

extern long program_entry(void);

void print_int(long x) {
    printf("%ld\n", x);
}

int main(void) {
    long result = program_entry();
    printf("RETVAL:%ld\n", result);
    return 0;
}
