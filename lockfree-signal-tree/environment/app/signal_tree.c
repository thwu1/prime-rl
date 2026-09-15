/*
 * signal_tree.c — Lock-free signal tree implementation
 *
 * TODO: Implement all functions declared in signal_tree.h
 *       according to the specification in spec.md.
 *
 * Hint: You will need <stdatomic.h> for C11 atomic operations.
 */

#include "signal_tree.h"
#include <stdlib.h>

/* Define the signal_tree struct and implement all API functions. */

struct signal_tree {
    int placeholder;
};

signal_tree_t *signal_tree_create(void) {
    return calloc(1, sizeof(signal_tree_t));
}

void signal_tree_destroy(signal_tree_t *tree) {
    free(tree);
}

st_set_result_t signal_tree_set(signal_tree_t *tree, uint64_t index) {
    (void)tree; (void)index;
    return (st_set_result_t){false, false};
}

st_select_result_t signal_tree_select(signal_tree_t *tree, uint64_t bias) {
    (void)tree; (void)bias;
    return (st_select_result_t){ST_INVALID_INDEX, false};
}

bool signal_tree_empty(const signal_tree_t *tree) {
    (void)tree;
    return true;
}
