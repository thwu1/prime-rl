#include <stdio.h>
#include <string.h>
#include <stdint.h>

uint32_t fnv1a_hash(const char *data, size_t len) {
    uint32_t hash = 2166136261u;
    for (size_t i = 0; i < len; i++) {
        hash ^= (uint8_t)data[i];
        hash *= 16777619u;
    }
    return hash;
}

uint32_t djb2_hash(const char *str) {
    uint32_t hash = 5381;
    int c;
    while ((c = *str++))
        hash = ((hash << 5) + hash) + c;
    return hash;
}

int hash_lookup(uint32_t *table, size_t table_size, uint32_t key) {
    uint32_t idx = key % table_size;
    for (size_t i = 0; i < table_size; i++) {
        uint32_t probe = (idx + i) % table_size;
        if (table[probe] == key)
            return (int)probe;
        if (table[probe] == 0)
            return -1;
    }
    return -1;
}
