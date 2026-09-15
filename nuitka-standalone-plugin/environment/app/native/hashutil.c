#include <stdio.h>
#include <string.h>
#include <stdint.h>

/* DJB2 hash function */
static uint64_t djb2(const char *str) {
    uint64_t hash = 5381;
    int c;
    while ((c = (unsigned char)*str++))
        hash = ((hash << 5) + hash) + c;
    return hash;
}

/* Compute hash and write hex representation to output buffer */
void hash_hex(const char *str, char *out, int out_len) {
    uint64_t h = djb2(str);
    snprintf(out, out_len, "%016llx", (unsigned long long)h);
}
