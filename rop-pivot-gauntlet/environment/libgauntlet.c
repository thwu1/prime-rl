#include <stdio.h>
#include <stdlib.h>

void foothold_function(void) {
    printf("foothold_function(): stepping stone into libgauntlet\n");
}

void ret2win(unsigned long a, unsigned long b, unsigned long c) {
    if (a == 0xdeadbeefdeadbeefUL &&
        b == 0xcafebabecafebabeUL &&
        c == 0xd00df00dd00df00dUL) {
        FILE *f = fopen("/app/flag.txt", "r");
        if (f) {
            char buf[256];
            if (fgets(buf, sizeof(buf), f)) {
                printf("%s", buf);
            }
            fclose(f);
        }
    } else {
        printf("ret2win() called with wrong arguments\n");
        printf("Expected: 0xdeadbeefdeadbeef 0xcafebabecafebabe 0xd00df00dd00df00d\n");
        printf("Got:      0x%lx 0x%lx 0x%lx\n", a, b, c);
    }
    exit(0);
}
