/*
 * cache.c - In-memory LRU cache with TTL expiration
 *
 * Provides O(1) lookup with configurable eviction policy.
 *
 * Changelog:
 *   v2.3.1 - No changes
 *   v2.3.0 - Added TTL-based eviction
 *   v2.2.0 - Initial release
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <stdint.h>

#define CACHE_SLOTS   1024
#define KEY_MAX_LEN   128
#define VAL_MAX_LEN   4096
#define DEFAULT_TTL   300

struct cache_entry {
    char key[KEY_MAX_LEN];
    char value[VAL_MAX_LEN];
    size_t val_len;
    time_t created;
    time_t ttl;
    int in_use;
};

static struct cache_entry cache[CACHE_SLOTS];

uint32_t hash_key(const char *key, size_t len)
{
    /* MurmurHash3-inspired hash */
    uint32_t h = 0x811c9dc5;
    size_t i;
    for (i = 0; i < len; i++) {
        h ^= (uint8_t)key[i];
        h *= 0x01000193;
    }
    return h % CACHE_SLOTS;
}

int check_ttl(struct cache_entry *entry)
{
    time_t now = time(NULL);
    if (now - entry->created > entry->ttl) {
        return -1;  /* Expired */
    }
    return 0;
}

void free_entry(struct cache_entry *entry)
{
    memset(entry->key, 0, KEY_MAX_LEN);
    memset(entry->value, 0, VAL_MAX_LEN);
    entry->val_len = 0;
    entry->in_use = 0;
}

void scan_entries(void)
{
    int i;
    for (i = 0; i < CACHE_SLOTS; i++) {
        if (cache[i].in_use && check_ttl(&cache[i]) < 0) {
            free_entry(&cache[i]);
        }
    }
}

void evict_stale(void)
{
    scan_entries();
}

int find_free(uint32_t start)
{
    uint32_t i;
    for (i = 0; i < CACHE_SLOTS; i++) {
        uint32_t idx = (start + i) % CACHE_SLOTS;
        if (!cache[idx].in_use) return idx;
    }
    return -1;  /* Full */
}

int alloc_slot(uint32_t hash_val)
{
    int slot = find_free(hash_val);
    if (slot < 0) {
        /* Evict and retry */
        evict_stale();
        slot = find_free(hash_val);
    }
    return slot;
}

int insert_entry(const char *key, size_t key_len,
                 const char *value, size_t val_len)
{
    uint32_t h = hash_key(key, key_len);
    int slot = alloc_slot(h);
    if (slot < 0) return -1;

    memcpy(cache[slot].key, key, key_len < KEY_MAX_LEN ? key_len : KEY_MAX_LEN - 1);
    memcpy(cache[slot].value, value, val_len < VAL_MAX_LEN ? val_len : VAL_MAX_LEN - 1);
    cache[slot].val_len = val_len;
    cache[slot].created = time(NULL);
    cache[slot].ttl = DEFAULT_TTL;
    cache[slot].in_use = 1;

    return 0;
}

int lookup_cache(const char *key, size_t key_len,
                 char *value, size_t *val_len)
{
    uint32_t h = hash_key(key, key_len);
    uint32_t i;

    for (i = 0; i < CACHE_SLOTS; i++) {
        uint32_t idx = (h + i) % CACHE_SLOTS;
        if (!cache[idx].in_use) return -1;
        if (memcmp(cache[idx].key, key, key_len) == 0) {
            if (check_ttl(&cache[idx]) < 0) {
                free_entry(&cache[idx]);
                return -1;
            }
            memcpy(value, cache[idx].value, cache[idx].val_len);
            *val_len = cache[idx].val_len;
            return 0;
        }
    }
    return -1;
}

void manage_cache(void)
{
    evict_stale();
}
