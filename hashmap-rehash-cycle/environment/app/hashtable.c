/* hashtable.c - Separate-chaining hash table implementation.
 *
 */

#include "hashtable.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

static unsigned int djb2_hash(const char *key) {
    unsigned int hash = 5381;
    int c;
    while ((c = *key++))
        hash = ((hash << 5) + hash) + c;
    return hash;
}

hashtable_t *ht_create(unsigned int initial_capacity) {
    hashtable_t *ht = malloc(sizeof(hashtable_t));
    if (!ht) return NULL;
    ht->capacity = initial_capacity;
    ht->size = 0;
    ht->max_load_factor = 0.75f;
    ht->buckets = calloc(initial_capacity, sizeof(ht_entry_t *));
    return ht;
}

void ht_destroy(hashtable_t *ht) {
    if (!ht) return;
    for (unsigned int i = 0; i < ht->capacity; i++) {
        ht_entry_t *e = ht->buckets[i];
        int safety = 0;
        while (e && safety < 100000) {
            ht_entry_t *next = e->next;
            free(e->key);
            free(e->value);
            free(e);
            e = next;
            safety++;
        }
    }
    free(ht->buckets);
    free(ht);
}

/* Rehash all entries from old_buckets into new_buckets. */
static void transfer(ht_entry_t **new_buckets, ht_entry_t **old_buckets,
                     unsigned int old_cap, unsigned int new_cap) {
    for (unsigned int j = 0; j < old_cap; j++) {
        ht_entry_t *e = old_buckets[j];
        if (e != NULL) {
            old_buckets[j] = NULL;
            do {
                ht_entry_t *next = e->next;
                unsigned int i = e->hash % new_cap;
                e->next = new_buckets[i];
                new_buckets[i] = e;
                e = next;
            } while (e != NULL);
        }
    }
}

static void ht_resize(hashtable_t *ht) {
    unsigned int new_cap = ht->capacity * 2;
    ht_entry_t **new_buckets = calloc(new_cap, sizeof(ht_entry_t *));
    if (!new_buckets) return;
    transfer(new_buckets, ht->buckets, ht->capacity, new_cap);
    free(ht->buckets);
    ht->buckets = new_buckets;
    ht->capacity = new_cap;
}

int ht_put(hashtable_t *ht, const char *key, const char *value) {
    unsigned int h = djb2_hash(key);
    unsigned int idx = h % ht->capacity;

    /* Check if key already exists */
    for (ht_entry_t *e = ht->buckets[idx]; e != NULL; e = e->next) {
        if (e->hash == h && strcmp(e->key, key) == 0) {
            free(e->value);
            e->value = strdup(value);
            return 0;  /* updated */
        }
    }

    /* Insert new entry at head of chain */
    ht_entry_t *entry = malloc(sizeof(ht_entry_t));
    if (!entry) return -1;
    entry->key = strdup(key);
    entry->value = strdup(value);
    entry->hash = h;
    entry->next = ht->buckets[idx];
    ht->buckets[idx] = entry;
    ht->size++;

    /* Check if resize is needed */
    if ((float)ht->size / (float)ht->capacity > ht->max_load_factor) {
        ht_resize(ht);
    }

    return 1;  /* inserted */
}

char *ht_get(hashtable_t *ht, const char *key) {
    unsigned int h = djb2_hash(key);
    unsigned int idx = h % ht->capacity;

    for (ht_entry_t *e = ht->buckets[idx]; e != NULL; e = e->next) {
        if (e->hash == h && strcmp(e->key, key) == 0) {
            return e->value;
        }
    }
    return NULL;
}

int ht_remove(hashtable_t *ht, const char *key) {
    unsigned int h = djb2_hash(key);
    unsigned int idx = h % ht->capacity;

    ht_entry_t *prev = NULL;
    for (ht_entry_t *e = ht->buckets[idx]; e != NULL; prev = e, e = e->next) {
        if (e->hash == h && strcmp(e->key, key) == 0) {
            if (prev) prev->next = e->next;
            else ht->buckets[idx] = e->next;
            free(e->key);
            free(e->value);
            free(e);
            ht->size--;
            return 1;
        }
    }
    return 0;
}
