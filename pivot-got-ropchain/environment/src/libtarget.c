#include <stdio.h>
#include <stdlib.h>

void foothold_function(void) {
    printf("foothold_function(): gain a foothold into libtarget\n");
}

void ret2win(unsigned long long a, unsigned long long b, unsigned long long c) {
    if (a == 0xdeadbeefdeadbeefULL &&
        b == 0xcafebabecafebabeULL &&
        c == 0xd00df00dd00df00dULL) {
        /* Flag is XOR-encoded to prevent trivial strings extraction */
        unsigned char enc[] = {
            0x13, 0x0e, 0x11, 0x04, 0x3a, 0x31, 0x70, 0x37,
            0x71, 0x35, 0x1e, 0x26, 0x71, 0x35, 0x1e, 0x33,
            0x72, 0x32, 0x71, 0x2d, 0x37, 0x72, 0x1e, 0x33,
            0x71, 0x31, 0x1e, 0x22, 0x29, 0x75, 0x70, 0x2f,
            0x1e, 0x2c, 0x75, 0x32, 0x35, 0x72, 0x33, 0x3c
        };
        char flag[48];
        int i;
        for (i = 0; i < 40; i++) {
            flag[i] = enc[i] ^ 0x41;
        }
        flag[40] = '\n';
        flag[41] = '\0';
        FILE *f = fopen("/app/flag.txt", "w");
        if (f) {
            fputs(flag, f);
            fclose(f);
        }
    }
    exit(0);
}
