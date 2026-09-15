/* stress_test.c - Multi-threaded stress test for the hash table.
 *
 * Creates 8 threads each inserting 5000 entries into a hash table
 * starting with capacity 2 (forcing many resizes). After all threads
 * complete, verifies all entries are present.
 *
 * If the hash table has correctness issues under concurrent access,
 * this test may hang or report missing entries.
 *
 */

#include "hashtable.h"
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define NUM_THREADS 8
#define OPS_PER_THREAD 5000

static hashtable_t *ht;

void *worker(void *arg) {
    int tid = *(int *)arg;
    char key[64], value[64];

    for (int i = 0; i < OPS_PER_THREAD; i++) {
        snprintf(key, sizeof(key), "t%d_k%d", tid, i);
        snprintf(value, sizeof(value), "v%d_%d", tid, i);
        ht_put(ht, key, value);
    }
    return NULL;
}

int main(void) {
    ht = ht_create(2);  /* Very small initial capacity to force many resizes */
    if (!ht) {
        fprintf(stderr, "Failed to create hash table\n");
        return 1;
    }

    pthread_t threads[NUM_THREADS];
    int tids[NUM_THREADS];

    printf("Starting %d threads, %d ops each (initial capacity=2)...\n",
           NUM_THREADS, OPS_PER_THREAD);

    for (int i = 0; i < NUM_THREADS; i++) {
        tids[i] = i;
        if (pthread_create(&threads[i], NULL, worker, &tids[i]) != 0) {
            perror("pthread_create");
            return 1;
        }
    }

    for (int i = 0; i < NUM_THREADS; i++) {
        pthread_join(threads[i], NULL);
    }

    printf("All threads completed. Verifying entries...\n");

    /* Verify all entries are present */
    int found = 0, missing = 0;
    char key[64];
    for (int t = 0; t < NUM_THREADS; t++) {
        for (int i = 0; i < OPS_PER_THREAD; i++) {
            snprintf(key, sizeof(key), "t%d_k%d", t, i);
            if (ht_get(ht, key) != NULL) {
                found++;
            } else {
                missing++;
            }
        }
    }

    printf("Results: found=%d, missing=%d, total=%d\n",
           found, missing, NUM_THREADS * OPS_PER_THREAD);

    if (missing == 0) {
        printf("PASS: All %d entries found and correct\n", found);
    } else {
        printf("FAIL: %d entries missing out of %d\n",
               missing, NUM_THREADS * OPS_PER_THREAD);
    }

    ht_destroy(ht);
    return (missing == 0) ? 0 : 1;
}
