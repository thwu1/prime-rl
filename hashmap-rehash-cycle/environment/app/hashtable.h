#ifndef HASHTABLE_H
#define HASHTABLE_H

typedef struct ht_entry {
    char *key;
    char *value;
    unsigned int hash;
    struct ht_entry *next;
} ht_entry_t;

typedef struct {
    ht_entry_t **buckets;
    unsigned int capacity;
    unsigned int size;
    float max_load_factor;
} hashtable_t;

hashtable_t *ht_create(unsigned int initial_capacity);
void ht_destroy(hashtable_t *ht);
int ht_put(hashtable_t *ht, const char *key, const char *value);
char *ht_get(hashtable_t *ht, const char *key);
int ht_remove(hashtable_t *ht, const char *key);

#endif
