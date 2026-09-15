#include <stdio.h>
#include <stdlib.h>
#include <inttypes.h>
#include <time.h>
#include "hashtable.h"

int main(int argc, char** argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <input_file>\n", argv[0]);
        return 1;
    }

    FILE* f = fopen(argv[1], "r");
    if (!f) {
        perror("fopen");
        return 1;
    }

    HashTable* ht = calloc(1, sizeof(HashTable));
    if (!ht) {
        fprintf(stderr, "Failed to allocate hash table\n");
        return 1;
    }
    ht_init(ht);

    struct timespec start, end;
    clock_gettime(CLOCK_MONOTONIC, &start);

    uint64_t key;
    int count = 0;
    while (fscanf(f, "%" SCNu64, &key) == 1) {
        if (ht_insert(ht, key, key) != 0) break;
        count++;
    }

    clock_gettime(CLOCK_MONOTONIC, &end);

    double elapsed = (end.tv_sec - start.tv_sec) +
                     (end.tv_nsec - start.tv_nsec) / 1e9;
    printf("Inserted %d keys in %.6f seconds\n", count, elapsed);

    rewind(f);
    int found = 0;
    while (fscanf(f, "%" SCNu64, &key) == 1 && found < count) {
        uint64_t val;
        if (ht_lookup(ht, key, &val) && val == key) found++;
    }
    printf("Verified %d/%d lookups\n", found, count);

    fclose(f);
    free(ht);
    return 0;
}
