#ifndef HASHTABLE_H
#define HASHTABLE_H

#include <stdint.h>
#include <stddef.h>

#define TABLE_BITS 16
#define TABLE_SIZE (1 << TABLE_BITS)
#define TABLE_MASK (TABLE_SIZE - 1)

typedef struct {
    uint64_t key;
    uint64_t value;
    uint8_t occupied;
} Entry;

typedef struct {
    Entry entries[TABLE_SIZE];
    size_t count;
} HashTable;

void ht_init(HashTable* ht);
int ht_insert(HashTable* ht, uint64_t key, uint64_t value);
int ht_lookup(const HashTable* ht, uint64_t key, uint64_t* value);
int ht_delete(HashTable* ht, uint64_t key);

#endif
