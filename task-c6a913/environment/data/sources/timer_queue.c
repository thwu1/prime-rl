#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct timer_entry {
    int id;
    int expires;
    char callback_name[32];
    int active;
};

struct timer_queue {
    struct timer_entry **timers;
    int capacity;
    int count;
};

struct timer_queue *tq_create(int capacity) {
    struct timer_queue *tq = (struct timer_queue *)malloc(sizeof(struct timer_queue));
    tq->timers = (struct timer_entry **)calloc(capacity, sizeof(struct timer_entry *));
    tq->capacity = capacity;
    tq->count = 0;
    return tq;
}

struct timer_entry *tq_add(struct timer_queue *tq, int id,
                            int expires, const char *cb_name)
{
    if (tq->count >= tq->capacity) return NULL;
    struct timer_entry *te = (struct timer_entry *)malloc(sizeof(struct timer_entry));
    te->id = id;
    te->expires = expires;
    strncpy(te->callback_name, cb_name, 31);
    te->callback_name[31] = '\0';
    te->active = 1;
    tq->timers[tq->count++] = te;
    return te;
}

/*
 * tq_expire_first - Expire and fire the first pending timer
 *
 * BUG: Frees the timer entry, then writes to the freed memory
 * (setting active=0 and expires=-1). This simulates a race
 * condition where the timer fires concurrently with a cancel
 * operation that frees the timer entry.
 */
void tq_expire_first(struct timer_queue *tq) {
    if (tq->count == 0) return;

    struct timer_entry *te = tq->timers[0];

    /* Remove from queue by shifting */
    for (int i = 0; i < tq->count - 1; i++)
        tq->timers[i] = tq->timers[i + 1];
    tq->timers[tq->count - 1] = NULL;
    tq->count--;

    /* Fire the callback */
    printf("firing timer %d: %s\n", te->id, te->callback_name);

    /* Simulate concurrent cancel freeing the entry */
    free(te);

    /* BUG: use-after-free writes to freed entry */
    te->active = 0;
    te->expires = -1;
}

void tq_destroy(struct timer_queue *tq) {
    for (int i = 0; i < tq->count; i++)
        free(tq->timers[i]);
    free(tq->timers);
    free(tq);
}

int main(void) {
    struct timer_queue *tq = tq_create(8);
    tq_add(tq, 1, 100, "process_io");
    tq_add(tq, 2, 200, "flush_cache");
    tq_add(tq, 3, 300, "gc_sweep");

    tq_expire_first(tq);
    printf("Remaining timers: %d\n", tq->count);

    tq_destroy(tq);
    return 0;
}
