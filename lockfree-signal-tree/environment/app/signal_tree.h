/*
 * signal_tree.h — Lock-free signal tree API
 *
 * A concurrent data structure managing 512 binary signals with
 * wait-free set and lock-free select operations.
 *
 * See spec.md for behavioral requirements.
 */

#ifndef SIGNAL_TREE_H
#define SIGNAL_TREE_H

#include <stdint.h>
#include <stdbool.h>

/* Public constants */
#define ST_CAPACITY            512
#define ST_INVALID_INDEX       UINT64_MAX

/* Opaque tree handle */
typedef struct signal_tree signal_tree_t;

/* Result of a set operation */
typedef struct {
    bool tree_was_empty;   /* Was the tree empty before this set? */
    bool signal_was_new;   /* Was this signal not previously active? */
} st_set_result_t;

/* Result of a select operation */
typedef struct {
    uint64_t index;        /* Selected signal (ST_INVALID_INDEX if tree empty) */
    bool     tree_is_empty;/* Did the tree become empty after this select? */
} st_select_result_t;

/* Allocate and initialize a new signal tree (all signals inactive). */
signal_tree_t *signal_tree_create(void);

/* Destroy a signal tree and free its memory. */
void signal_tree_destroy(signal_tree_t *tree);

/* Activate signal 'index' (0 <= index < ST_CAPACITY). Wait-free. */
st_set_result_t signal_tree_set(signal_tree_t *tree, uint64_t index);

/* Select and deactivate one active signal, guided by 'bias'. Lock-free.
 * Returns ST_INVALID_INDEX if the tree is empty. */
st_select_result_t signal_tree_select(signal_tree_t *tree, uint64_t bias);

/* Returns true if no signals are active. */
bool signal_tree_empty(const signal_tree_t *tree);

#endif /* SIGNAL_TREE_H */
