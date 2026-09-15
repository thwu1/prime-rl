#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>

#define NUM_FUNCS 8

extern void run_v1(const uint8_t *data, size_t len, uint32_t results[NUM_FUNCS]);
extern void run_v2(const uint8_t *data, size_t len, uint32_t results[NUM_FUNCS]);

static const char *func_names[NUM_FUNCS] = {
    "checksum_adler32",
    "checksum_crc32",
    "checksum_djb2",
    "checksum_fletcher16",
    "checksum_fnv1a",
    "checksum_rotxor",
    "checksum_sdbm",
    "checksum_xor8"
};

int main(void) {
    const uint8_t *test_data =
        (const uint8_t *)"The quick brown fox jumps over the lazy dog";
    size_t len = strlen((const char *)test_data);

    uint32_t v1[NUM_FUNCS], v2[NUM_FUNCS];
    run_v1(test_data, len, v1);
    run_v2(test_data, len, v2);

    FILE *f = fopen("results.txt", "w");
    if (!f) {
        perror("fopen");
        return 1;
    }

    for (int i = 0; i < NUM_FUNCS; i++) {
        if (v1[i] != v2[i]) {
            fprintf(f, "%s\n", func_names[i]);
            printf("DIFF %s: v1=0x%08x v2=0x%08x\n",
                   func_names[i], v1[i], v2[i]);
        } else {
            printf("SAME %s: 0x%08x\n", func_names[i], v1[i]);
        }
    }

    fclose(f);
    printf("\nResults written to results.txt\n");
    return 0;
}
