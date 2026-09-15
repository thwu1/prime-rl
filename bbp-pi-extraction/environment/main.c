#include <stdio.h>
#include <stdlib.h>
#include "pi_extract.h"

int main(int argc, char *argv[])
{
    long position;
    int count, i, digit;

    if (argc != 3) {
        fprintf(stderr, "Usage: %s <position> <count>\n", argv[0]);
        return 1;
    }

    position = atol(argv[1]);
    count = atoi(argv[2]);

    if (position < 0 || count <= 0) {
        fprintf(stderr, "Error: position >= 0, count > 0 required\n");
        return 1;
    }

    for (i = 0; i < count; i++) {
        digit = pi_hex_digit(position + i);
        if (digit < 0 || digit > 15) {
            fprintf(stderr, "Error at position %ld\n", position + i);
            return 1;
        }
        printf("%X", digit);
    }
    printf("\n");
    return 0;
}
