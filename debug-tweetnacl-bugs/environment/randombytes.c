#include <stdio.h>
#include <stdlib.h>

void randombytes(unsigned char *x, unsigned long long xlen) {
    FILE *f = fopen("/dev/urandom", "r");
    if (!f) { perror("randombytes: /dev/urandom"); exit(1); }
    if (fread(x, 1, (size_t)xlen, f) != (size_t)xlen) {
        perror("randombytes: read");
        fclose(f);
        exit(1);
    }
    fclose(f);
}
