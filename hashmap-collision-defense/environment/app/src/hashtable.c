#include "hashtable.h"
#include <string.h>

static const uint64_t HASH_MULT = 0x517cc1b727220a95ULL;

static uint32_t hash_key(uint64_t key) {
    return (uint32_t)((key * HASH_MULT) >> (64 - TABLE_BITS));
}

void ht_init(HashTable* ht) {
    memset(ht, 0, sizeof(HashTable));
}

int ht_insert(HashTable* ht, uint64_t key, uint64_t value) {
    if (ht->count >= TABLE_SIZE * 3 / 4)
        return -1;
    uint32_t idx = hash_key(key);
    for (;;) {
        uint32_t i = idx & TABLE_MASK;
        if (!ht->entries[i].occupied) {
            ht->entries[i].key = key;
            ht->entries[i].value = value;
            ht->entries[i].occupied = 1;
            ht->count++;
            return 0;
        }
        if (ht->entries[i].key == key) {
            ht->entries[i].value = value;
            return 0;
        }
        idx++;
    }
}

int ht_lookup(const HashTable* ht, uint64_t key, uint64_t* value) {
    uint32_t idx = hash_key(key);
    for (;;) {
        uint32_t i = idx & TABLE_MASK;
        if (!ht->entries[i].occupied)
            return 0;
        if (ht->entries[i].key == key) {
            if (value) *value = ht->entries[i].value;
            return 1;
        }
        idx++;
    }
}

int ht_delete(HashTable* ht, uint64_t key) {
    uint32_t idx = hash_key(key);
    for (;;) {
        uint32_t i = idx & TABLE_MASK;
        if (!ht->entries[i].occupied)
            return 0;
        if (ht->entries[i].key == key) {
            ht->entries[i].occupied = 0;
            ht->count--;
            /* backward-shift to maintain linear-probing chains */
            uint32_t j = (i + 1) & TABLE_MASK;
            while (ht->entries[j].occupied) {
                uint32_t natural = hash_key(ht->entries[j].key) & TABLE_MASK;
                int should_move;
                if (i <= j)
                    should_move = (natural <= i) || (natural > j);
                else
                    should_move = (natural <= i) && (natural > j);
                if (should_move) {
                    ht->entries[i] = ht->entries[j];
                    ht->entries[j].occupied = 0;
                    i = j;
                }
                j = (j + 1) & TABLE_MASK;
            }
            return 1;
        }
        idx++;
    }
}
