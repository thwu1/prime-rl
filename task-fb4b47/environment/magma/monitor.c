#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "storage.h"

int main(void) {
    const char *path = "/tmp/magma_canaries.bin";

    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "monitor: cannot open %s\n", path);
        return 1;
    }

    magma_storage_t s;
    memset(&s, 0, sizeof(s));
    size_t nread = fread(&s, 1, sizeof(s), f);
    fclose(f);

    if (nread < 8) {
        fprintf(stderr, "monitor: file too small (%zu bytes)\n", nread);
        return 1;
    }

    if (s.magic != MAGMA_STORAGE_MAGIC) {
        fprintf(stderr, "monitor: bad magic 0x%08X\n", s.magic);
        return 1;
    }

    printf("bug_id,reached,triggered\n");
    for (uint32_t i = 0; i < s.num_bugs && i < MAGMA_MAX_BUGS; i++) {
        printf("%s,%u,%u\n", s.bugs[i].id, s.bugs[i].reached, s.bugs[i].triggered);
    }

    return 0;
}
