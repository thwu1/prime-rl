/* hashtable.c - Thread-safe separate-chaining hash table.
 *
 * Fixed version: uses a pthread_rwlock_t to protect all operations.
 * Write lock is held during ht_put (including resize), ht_remove, and ht_destroy.
 * Read lock is held during ht_get, allowing concurrent reads.
 *
 * This prevents the circular linked list bug that occurs when two threads
 * concurrently execute transfer() during resize — since only one thread can
 * hold the write lock, only one resize can execute at a time, and no reads
 * can occur during resize.
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
    if (!ht->buckets) {
        free(ht);
        return NULL;
    }
    pthread_rwlock_init(&ht->lock, NULL);
    return ht;
}

void ht_destroy(hashtable_t *ht) {
    if (!ht) return;
    pthread_rwlock_wrlock(&ht->lock);
    for (unsigned int i = 0; i < ht->capacity; i++) {
        ht_entry_t *e = ht->buckets[i];
        while (e) {
            ht_entry_t *next = e->next;
            free(e->key);
            free(e->value);
            free(e);
            e = next;
        }
    }
    free(ht->buckets);
    pthread_rwlock_unlock(&ht->lock);
    pthread_rwlock_destroy(&ht->lock);
    free(ht);
}

static void transfer(ht_entry_t **new_buckets, ht_entry_t **old_buckets,
                     unsigned int old_cap, unsigned int new_cap) {
    for (unsigned int j = 0; j < old_cap; j++) {
        ht_entry_t *e = old_buckets[j];
        old_buckets[j] = NULL;
        while (e != NULL) {
            ht_entry_t *next = e->next;
            unsigned int i = e->hash % new_cap;
            e->next = new_buckets[i];
            new_buckets[i] = e;
            e = next;
        }
    }
}

static void ht_resize(hashtable_t *ht) {
    /* Called with write lock already held by ht_put */
    unsigned int new_cap = ht->capacity * 2;
    ht_entry_t **new_buckets = calloc(new_cap, sizeof(ht_entry_t *));
    if (!new_buckets) return;
    transfer(new_buckets, ht->buckets, ht->capacity, new_cap);
    free(ht->buckets);
    ht->buckets = new_buckets;
    ht->capacity = new_cap;
}

int ht_put(hashtable_t *ht, const char *key, const char *value) {
    pthread_rwlock_wrlock(&ht->lock);

    unsigned int h = djb2_hash(key);
    unsigned int idx = h % ht->capacity;

    /* Check if key already exists */
    for (ht_entry_t *e = ht->buckets[idx]; e != NULL; e = e->next) {
        if (e->hash == h && strcmp(e->key, key) == 0) {
            free(e->value);
            e->value = strdup(value);
            pthread_rwlock_unlock(&ht->lock);
            return 0;  /* updated */
        }
    }

    /* Insert new entry at HEAD of chain */
    ht_entry_t *entry = malloc(sizeof(ht_entry_t));
    if (!entry) {
        pthread_rwlock_unlock(&ht->lock);
        return -1;
    }
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

    pthread_rwlock_unlock(&ht->lock);
    return 1;  /* inserted */
}

char *ht_get(hashtable_t *ht, const char *key) {
    pthread_rwlock_rdlock(&ht->lock);

    unsigned int h = djb2_hash(key);
    unsigned int idx = h % ht->capacity;

    for (ht_entry_t *e = ht->buckets[idx]; e != NULL; e = e->next) {
        if (e->hash == h && strcmp(e->key, key) == 0) {
            char *val = e->value;
            pthread_rwlock_unlock(&ht->lock);
            return val;
        }
    }

    pthread_rwlock_unlock(&ht->lock);
    return NULL;
}

int ht_remove(hashtable_t *ht, const char *key) {
    pthread_rwlock_wrlock(&ht->lock);

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
            pthread_rwlock_unlock(&ht->lock);
            return 1;
        }
    }

    pthread_rwlock_unlock(&ht->lock);
    return 0;
}
