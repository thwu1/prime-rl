/* simulate.c — Simulates the concurrent rehash interleaving from scenario.txt.
 *
 * Models the exact thread interleaving step by step to show how head-insertion
 * rehash creates a circular linked list when two threads resize simultaneously.
 *
 */

#include <stdio.h>
#include <stdlib.h>

typedef struct entry {
    const char *key;
    unsigned int hash;
    struct entry *next;
} entry_t;

int main(void) {
    /* Create the two entries from the scenario */
    entry_t e_a = { .key = "alpha", .hash = 3, .next = NULL };
    entry_t e_b = { .key = "bravo", .hash = 7, .next = NULL };

    unsigned int old_cap = 2;
    unsigned int new_cap = 4;

    /* Initial state: bucket[1] = E_a -> E_b -> NULL */
    e_a.next = &e_b;
    e_b.next = NULL;

    printf("=== INITIAL STATE ===\n");
    printf("Capacity: %u\n", old_cap);
    printf("Bucket[1]: %s(hash=%u) -> %s(hash=%u) -> NULL\n",
           e_a.key, e_a.hash, e_b.key, e_b.hash);
    printf("New bucket assignments: %u%%%u=%u, %u%%%u=%u\n\n",
           e_a.hash, new_cap, e_a.hash % new_cap,
           e_b.hash, new_cap, e_b.hash % new_cap);

    /* ---- Thread_A starts transfer, then is SUSPENDED ---- */
    entry_t *ta_e = &e_a;
    entry_t *ta_next = e_a.next;  /* = &e_b, saved before suspend */

    printf("=== THREAD_A STARTS ===\n");
    printf("Thread_A: e = %s, next = %s  [SUSPENDED]\n\n", ta_e->key, ta_next->key);

    /* ---- Thread_B completes entire transfer ---- */
    entry_t *new_b[4] = {NULL, NULL, NULL, NULL};

    printf("=== THREAD_B COMPLETES TRANSFER ===\n");

    /* Thread_B iteration 1: process E_a */
    entry_t *tb_e = &e_a;
    entry_t *tb_next = tb_e->next;  /* E_b */
    unsigned int tb_i = tb_e->hash % new_cap;
    printf("  Iter 1: e=%s, next=%s\n", tb_e->key, tb_next->key);
    tb_e->next = new_b[tb_i];      /* E_a->next = NULL */
    new_b[tb_i] = tb_e;            /* new_b[3] = E_a */
    printf("    %s->next = NULL, new_b[%u] = %s\n", tb_e->key, tb_i, tb_e->key);
    tb_e = tb_next;

    /* Thread_B iteration 2: process E_b */
    tb_next = tb_e->next;          /* NULL (original end of chain) */
    tb_i = tb_e->hash % new_cap;
    printf("  Iter 2: e=%s, next=NULL\n", tb_e->key);
    tb_e->next = new_b[tb_i];      /* E_b->next = E_a */
    new_b[tb_i] = tb_e;            /* new_b[3] = E_b */
    printf("    %s->next = %s, new_b[%u] = %s\n",
           tb_e->key, tb_e->next->key, tb_i, tb_e->key);

    printf("\n  After Thread_B: new_b[3]: %s -> %s -> NULL\n",
           new_b[3]->key, new_b[3]->next->key);
    printf("  Pointer state: %s->next = %s, %s->next = %s\n\n",
           e_a.key, e_a.next ? e_a.next->key : "NULL",
           e_b.key, e_b.next ? e_b.next->key : "NULL");

    /* ---- Thread_A resumes ---- */
    entry_t *new_a[4] = {NULL, NULL, NULL, NULL};

    printf("=== THREAD_A RESUMES (e=%s, next=%s) ===\n", ta_e->key, ta_next->key);

    /* Thread_A iteration 1: process E_a */
    ta_e = &e_a;  /* still E_a from before suspend */
    unsigned int ta_i = ta_e->hash % new_cap;
    printf("  Iter 1: e=%s (hash=%u, bucket=%u)\n", ta_e->key, ta_e->hash, ta_i);
    ta_e->next = new_a[ta_i];      /* E_a->next = NULL (new_a[3] is empty) */
    new_a[ta_i] = ta_e;            /* new_a[3] = E_a */
    printf("    %s->next = NULL, new_a[%u] = %s\n", ta_e->key, ta_i, ta_e->key);
    ta_e = ta_next;                /* E_b (saved before suspend) */

    /* Thread_A iteration 2: process E_b */
    ta_next = ta_e->next;          /* E_b->next = E_a (set by Thread_B!) */
    ta_i = ta_e->hash % new_cap;
    printf("  Iter 2: e=%s (hash=%u, bucket=%u)\n", ta_e->key, ta_e->hash, ta_i);
    printf("    *** next = %s->next = %s (MODIFIED BY THREAD_B!) ***\n",
           ta_e->key, ta_next ? ta_next->key : "NULL");
    ta_e->next = new_a[ta_i];      /* E_b->next = new_a[3] = E_a */
    new_a[ta_i] = ta_e;            /* new_a[3] = E_b */
    printf("    %s->next = %s, new_a[%u] = %s\n",
           ta_e->key, ta_e->next->key, ta_i, ta_e->key);
    printf("    new_a[3]: %s -> %s -> NULL (so far no cycle)\n",
           new_a[3]->key, new_a[3]->next->key);
    ta_e = ta_next;                /* E_a (not NULL!) */
    printf("    e = next = %s  (NOT NULL — loop continues!)\n\n", ta_e->key);

    /* Thread_A iteration 3: process E_a AGAIN! */
    ta_next = ta_e->next;          /* E_a->next = NULL (set by Thread_A iter 1) */
    ta_i = ta_e->hash % new_cap;
    printf("  Iter 3: e=%s AGAIN! (hash=%u, bucket=%u)\n", ta_e->key, ta_e->hash, ta_i);
    printf("    next = %s->next = %s\n", ta_e->key, ta_next ? ta_next->key : "NULL");
    ta_e->next = new_a[ta_i];      /* E_a->next = new_a[3] = E_b  => CYCLE! */
    new_a[ta_i] = ta_e;            /* new_a[3] = E_a */
    printf("    %s->next = %s  *** CYCLE FORMED! ***\n", ta_e->key, ta_e->next->key);
    ta_e = ta_next;                /* NULL — loop ends */

    printf("\n=== FINAL STATE ===\n");
    printf("Bucket 3: %s -> %s -> %s -> ... (infinite cycle)\n",
           new_a[3]->key, new_a[3]->next->key, new_a[3]->next->next->key);
    printf("%s->next = %s\n", e_a.key, e_a.next->key);
    printf("%s->next = %s\n", e_b.key, e_b.next->key);

    /* Verify cycle with Floyd's algorithm */
    entry_t *slow = new_a[3];
    entry_t *fast = new_a[3];
    int cycle_found = 0;
    for (int steps = 0; steps < 100; steps++) {
        if (!fast || !fast->next) break;
        slow = slow->next;
        fast = fast->next->next;
        if (slow == fast) {
            cycle_found = 1;
            break;
        }
    }
    printf("\nFloyd's cycle detection: %s\n",
           cycle_found ? "CYCLE CONFIRMED" : "NO CYCLE (unexpected)");

    printf("\nCYCLE_BUCKET=3\n");
    printf("CYCLE_ENTRIES=alpha,bravo\n");

    return 0;
}
