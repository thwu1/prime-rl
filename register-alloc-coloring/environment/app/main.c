#include <stdio.h>

extern long program(void);

int main(void) {
    long result = program();
    printf("%ld\n", result);
    return 0;
}
