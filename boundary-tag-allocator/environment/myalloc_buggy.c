/* myalloc.c - custom memory allocator
 * Build: gcc -O2 -fPIC -shared -o libmyalloc.so myalloc.c
 * Usage: LD_PRELOAD=./libmyalloc.so <program>
 */

#include <unistd.h>
#include <string.h>
#include <stdint.h>

struct block_hdr {
    size_t            size;
    int               is_free;
    struct block_hdr *next;
};

static struct block_hdr *head = NULL;

static struct block_hdr *find_free(struct block_hdr **last, size_t size) {
    struct block_hdr *cur = head;
    while (cur) {
        if (cur->is_free && cur->size >= size)
            return cur;
        *last = cur;
        cur   = cur->next;
    }
    return NULL;
}

static struct block_hdr *grow_heap(struct block_hdr *last, size_t size) {
    struct block_hdr *blk = sbrk(0);
    if (sbrk(sizeof(struct block_hdr) + size) == (void *)-1)
        return NULL;
    blk->size    = size;
    blk->is_free = 0;
    blk->next    = NULL;
    if (last)
        last->next = blk;
    return blk;
}

void *malloc(size_t size) {
    if (size == 0)
        return NULL;

    struct block_hdr *blk;
    if (!head) {
        blk = grow_heap(NULL, size);
        if (!blk) return NULL;
        head = blk;
    } else {
        struct block_hdr *last = head;
        blk = find_free(&last, size);
        if (blk) {
            blk->is_free = 0;
        } else {
            blk = grow_heap(last, size);
            if (!blk) return NULL;
        }
    }
    return (void *)(blk + 1);
}

void free(void *ptr) {
    struct block_hdr *blk = (struct block_hdr *)ptr - 1;
    blk->is_free = 1;
}

void *calloc(size_t nmemb, size_t size) {
    if (!nmemb || !size) return NULL;
    size_t total = nmemb * size;
    void *p = malloc(total);
    if (p) memset(p, 0, total);
    return p;
}

void *realloc(void *ptr, size_t size) {
    if (size == 0) {
        free(ptr);
        return NULL;
    }
    struct block_hdr *blk = (struct block_hdr *)ptr - 1;
    if (blk->size >= size)
        return ptr;
    void *newp = malloc(size);
    if (!newp) return NULL;
    memcpy(newp, ptr, blk->size);
    free(ptr);
    return newp;
}
