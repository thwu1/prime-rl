/* detect_cycle.c — Cycle detection for linked list chains using Floyd's algorithm.
 *
 * Demonstrates detection of circular linked lists (as caused by the concurrent
 * hash table rehash bug) and verifies no false positives on normal lists.
 *
 */

#include <stdio.h>
#include <stdlib.h>

typedef struct node {
    const char *key;
    struct node *next;
} node_t;

/* Floyd's tortoise-and-hare cycle detection.
 * Returns 1 if a cycle is detected, 0 otherwise. */
int has_cycle(node_t *head) {
    if (!head || !head->next) return 0;
    node_t *slow = head;
    node_t *fast = head;
    while (fast && fast->next) {
        slow = slow->next;
        fast = fast->next->next;
        if (slow == fast) return 1;
    }
    return 0;
}

/* Find the entry node where the cycle begins.
 * Returns NULL if no cycle exists. */
node_t *find_cycle_start(node_t *head) {
    if (!head || !head->next) return NULL;
    node_t *slow = head;
    node_t *fast = head;
    while (fast && fast->next) {
        slow = slow->next;
        fast = fast->next->next;
        if (slow == fast) {
            slow = head;
            while (slow != fast) {
                slow = slow->next;
                fast = fast->next;
            }
            return slow;
        }
    }
    return NULL;
}

/* Test 1: Two-node mutual cycle (as produced by the rehash bug) */
void test_mutual_cycle(void) {
    printf("=== Test 1: Two-node mutual cycle (rehash bug pattern) ===\n");
    node_t a = { .key = "alpha", .next = NULL };
    node_t b = { .key = "bravo", .next = NULL };
    a.next = &b;
    b.next = &a;  /* cycle: a <-> b */

    if (has_cycle(&a)) {
        node_t *start = find_cycle_start(&a);
        printf("CYCLE_FOUND: cycle starts at '%s'\n", start->key);
    } else {
        printf("ERROR: cycle not detected\n");
    }
}

/* Test 2: Normal list with no cycle */
void test_no_cycle(void) {
    printf("\n=== Test 2: Normal list (no cycle) ===\n");
    node_t a = { .key = "alpha", .next = NULL };
    node_t b = { .key = "bravo", .next = NULL };
    node_t c = { .key = "charlie", .next = NULL };
    a.next = &b;
    b.next = &c;
    c.next = NULL;

    if (has_cycle(&a)) {
        printf("ERROR: false positive\n");
    } else {
        printf("NO_CYCLE: correctly identified acyclic list\n");
    }
}

/* Test 3: Self-cycle (single node pointing to itself) */
void test_self_cycle(void) {
    printf("\n=== Test 3: Single-node self-cycle ===\n");
    node_t a = { .key = "alpha", .next = NULL };
    a.next = &a;

    if (has_cycle(&a)) {
        printf("CYCLE_FOUND: self-cycle detected at '%s'\n", a.key);
    } else {
        printf("ERROR: self-cycle not detected\n");
    }
}

/* Test 4: Long tail with cycle at the end */
void test_tail_cycle(void) {
    printf("\n=== Test 4: Long chain with tail cycle ===\n");
    node_t nodes[8];
    for (int i = 0; i < 8; i++) {
        nodes[i].key = "node";
        nodes[i].next = (i < 7) ? &nodes[i + 1] : &nodes[4];
    }
    /* Chain: 0->1->2->3->4->5->6->7->4 (cycle at node 4) */

    if (has_cycle(&nodes[0])) {
        node_t *start = find_cycle_start(&nodes[0]);
        printf("CYCLE_FOUND: tail cycle detected, starts at index %ld\n",
               start - nodes);
    } else {
        printf("ERROR: tail cycle not detected\n");
    }
}

/* Test 5: Single node, no cycle */
void test_single_node(void) {
    printf("\n=== Test 5: Single node (no cycle) ===\n");
    node_t a = { .key = "solo", .next = NULL };

    if (has_cycle(&a)) {
        printf("ERROR: false positive on single node\n");
    } else {
        printf("NO_CYCLE: single node correctly identified as acyclic\n");
    }
}

int main(void) {
    test_mutual_cycle();
    test_no_cycle();
    test_self_cycle();
    test_tail_cycle();
    test_single_node();

    printf("\nAll cycle detection tests completed.\n");
    return 0;
}
