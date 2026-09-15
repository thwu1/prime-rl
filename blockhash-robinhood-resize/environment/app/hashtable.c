/*
 *
 * Cache-Line-Aligned Hash Table — stub implementation.
 * Replace this file with a working implementation.
 */

#include "hashtable.h"
#include <stdlib.h>

struct bht {
    uint64_t placeholder;
};

bht_t *bht_create(uint32_t initial_capacity) {
    (void)initial_capacity;
    return NULL;
}

void bht_destroy(bht_t *ht) {
    (void)ht;
}

int bht_insert(bht_t *ht, const void *key, uint32_t key_len,
               const void *value, uint32_t value_len) {
    (void)ht; (void)key; (void)key_len; (void)value; (void)value_len;
    return -1;
}

int bht_lookup(bht_t *ht, const void *key, uint32_t key_len,
               void **value_out, uint32_t *value_len_out) {
    (void)ht; (void)key; (void)key_len; (void)value_out; (void)value_len_out;
    return -1;
}

int bht_delete(bht_t *ht, const void *key, uint32_t key_len) {
    (void)ht; (void)key; (void)key_len;
    return -1;
}

uint64_t bht_count(bht_t *ht) { (void)ht; return 0; }
double bht_load_factor(bht_t *ht) { (void)ht; return 0.0; }
uint64_t bht_memory_usage(bht_t *ht) { (void)ht; return 0; }
int bht_is_resizing(bht_t *ht) { (void)ht; return 0; }
double bht_avg_probe_distance(bht_t *ht) { (void)ht; return 0.0; }
int bht_verify_alignment(bht_t *ht) { (void)ht; return 0; }
