#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define NAME_MAX_LEN 64

struct inode_entry {
    unsigned long ino;
    char name[NAME_MAX_LEN];
    int ref_count;
};

struct inode_cache {
    struct inode_entry **slots;
    int size;
    int used;
};

struct inode_cache *icache_create(int size) {
    struct inode_cache *ic = (struct inode_cache *)malloc(sizeof(struct inode_cache));
    ic->slots = (struct inode_entry **)calloc(size, sizeof(struct inode_entry *));
    ic->size = size;
    ic->used = 0;
    return ic;
}

struct inode_entry *icache_insert(struct inode_cache *ic,
                                  unsigned long ino, const char *name)
{
    if (ic->used >= ic->size) return NULL;
    struct inode_entry *e = (struct inode_entry *)malloc(sizeof(struct inode_entry));
    e->ino = ino;
    strncpy(e->name, name, NAME_MAX_LEN - 1);
    e->name[NAME_MAX_LEN - 1] = '\0';
    e->ref_count = 1;
    ic->slots[ic->used++] = e;
    return e;
}

/*
 * icache_evict_oldest - Evict the oldest cache entry and return its ino
 *
 * BUG: Frees the victim entry then reads from it (use-after-free).
 * This simulates a race where eviction and lookup overlap, causing
 * the lookup path to access an entry freed by the eviction path.
 */
unsigned long icache_evict_oldest(struct inode_cache *ic) {
    if (ic->used == 0) return 0;

    struct inode_entry *victim = ic->slots[0];
    /* Shift entries down to fill the gap */
    for (int i = 0; i < ic->used - 1; i++)
        ic->slots[i] = ic->slots[i + 1];
    ic->slots[ic->used - 1] = NULL;
    ic->used--;

    /* Free the entry */
    free(victim);

    /* BUG: use-after-free reads from the freed entry */
    unsigned long evicted_ino = victim->ino;
    printf("evicted inode %lu: %s\n", evicted_ino, victim->name);
    return evicted_ino;
}

void icache_destroy(struct inode_cache *ic) {
    for (int i = 0; i < ic->used; i++)
        free(ic->slots[i]);
    free(ic->slots);
    free(ic);
}

int main(void) {
    struct inode_cache *ic = icache_create(8);
    icache_insert(ic, 1001, "file_alpha.txt");
    icache_insert(ic, 1002, "file_beta.txt");
    icache_insert(ic, 1003, "file_gamma.txt");

    unsigned long ino = icache_evict_oldest(ic);
    printf("Result: %lu\n", ino);

    icache_destroy(ic);
    return 0;
}
