/*
 * signal_tree.c — Lock-free signal tree (correct implementation)
 *
 * 512-signal concurrent data structure using atomic operations.
 *
 */

#include "signal_tree.h"
#include <stdlib.h>
#include <stdatomic.h>
#include <string.h>

/* ------------------------------------------------------------------ */
/* Internal constants                                                  */
/* ------------------------------------------------------------------ */
#define ST_LEAF_CAPACITY       64
#define ST_NUM_LEAVES          (ST_CAPACITY / ST_LEAF_CAPACITY)
#define ST_COUNTERS_PER_NODE   8
#define ST_BITS_PER_COUNTER    7

/* ------------------------------------------------------------------ */
/* Internal structure                                                  */
/* ------------------------------------------------------------------ */
struct signal_tree {
    _Atomic uint64_t root;
    _Atomic uint64_t leaves[ST_NUM_LEAVES];
};

/* ------------------------------------------------------------------ */
/* Packed-counter helpers                                               */
/* ------------------------------------------------------------------ */

/*
 * Addend table.  Counter i occupies bits [(7-i)*7 .. (7-i)*7+6].
 * Adding addend[i] to the root word increments counter i by 1.
 */
static const uint64_t addend[ST_COUNTERS_PER_NODE] = {
    1ULL << (7 * ST_BITS_PER_COUNTER),   /* counter 0 */
    1ULL << (6 * ST_BITS_PER_COUNTER),   /* counter 1 */
    1ULL << (5 * ST_BITS_PER_COUNTER),   /* counter 2 */
    1ULL << (4 * ST_BITS_PER_COUNTER),   /* counter 3 */
    1ULL << (3 * ST_BITS_PER_COUNTER),   /* counter 4 */
    1ULL << (2 * ST_BITS_PER_COUNTER),   /* counter 5 */
    1ULL << (1 * ST_BITS_PER_COUNTER),   /* counter 6 */
    1ULL << (0 * ST_BITS_PER_COUNTER),   /* counter 7 */
};

static const uint64_t COUNTER_MASK = (1ULL << ST_BITS_PER_COUNTER) - 1;

/* Extract the value of counter idx from a packed root word. */
static inline uint64_t get_counter(uint64_t root_val, int idx)
{
    return (root_val >> ((ST_COUNTERS_PER_NODE - 1 - idx)
                         * ST_BITS_PER_COUNTER)) & COUNTER_MASK;
}

/* ------------------------------------------------------------------ */
/* Bias-based selection helpers                                        */
/* ------------------------------------------------------------------ */

/*
 * Hierarchical binary selection among 8 packed counters.
 * Uses 3 low bits of `bias` to prefer left vs right halves.
 * Returns the index [0..7] of a non-zero counter, or -1 if none.
 */
static int select_counter(uint64_t value, uint64_t bias)
{
    if (value == 0) return -1;

    int base  = 0;
    int count = ST_COUNTERS_PER_NODE;

    for (int level = 0; count > 1; level++) {
        int half = count / 2;

        int left_nz = 0;
        for (int i = base; i < base + half; i++)
            if (get_counter(value, i)) { left_nz = 1; break; }

        int right_nz = 0;
        for (int i = base + half; i < base + count; i++)
            if (get_counter(value, i)) { right_nz = 1; break; }

        int prefer_right = (bias >> level) & 1;

        if (prefer_right && right_nz)
            base += half;
        else if (left_nz)
            ; /* stay in left half */
        else
            base += half; /* left empty, must go right */

        count = half;
    }
    return base;
}

/*
 * Select a set bit from a 64-bit bitmask using bias-based rotation.
 */
static int select_bit(uint64_t value, uint64_t bias)
{
    if (value == 0) return -1;

    int rotation = (int)((bias >> 3) & 63);
    uint64_t rotated;
    if (rotation == 0) {
        rotated = value;
    } else {
        rotated = (value >> rotation) | (value << (64 - rotation));
    }
    int bit = __builtin_ctzll(rotated);
    return (bit + rotation) & 63;
}

/* ------------------------------------------------------------------ */
/* Public API                                                          */
/* ------------------------------------------------------------------ */

signal_tree_t *signal_tree_create(void)
{
    signal_tree_t *tree = calloc(1, sizeof(signal_tree_t));
    if (!tree) return NULL;
    atomic_init(&tree->root, 0);
    for (int i = 0; i < ST_NUM_LEAVES; i++)
        atomic_init(&tree->leaves[i], 0);
    return tree;
}

void signal_tree_destroy(signal_tree_t *tree)
{
    free(tree);
}

st_set_result_t signal_tree_set(signal_tree_t *tree, uint64_t index)
{
    uint64_t leaf_idx = index / ST_LEAF_CAPACITY;
    uint64_t bit_idx  = index % ST_LEAF_CAPACITY;
    uint64_t bit_mask = 1ULL << bit_idx;

    /* Atomically set the leaf bit. */
    uint64_t old_leaf = atomic_fetch_or(&tree->leaves[leaf_idx], bit_mask);

    if (old_leaf & bit_mask) {
        /* Bit was already set — duplicate set, no root update. */
        return (st_set_result_t){ false, false };
    }

    /* Newly set — increment the root counter for this subtree. */
    uint64_t old_root = atomic_fetch_add(&tree->root, addend[leaf_idx]);
    return (st_set_result_t){ old_root == 0, true };
}

st_select_result_t signal_tree_select(signal_tree_t *tree, uint64_t bias)
{
    uint64_t expected = atomic_load(&tree->root);

    while (expected != 0) {
        int ci = select_counter(expected, bias);
        if (ci < 0) break;

        uint64_t desired = expected - addend[ci];

        if (atomic_compare_exchange_strong(&tree->root, &expected, desired)) {
            /*
             * Successfully claimed one signal from subtree ci.
             * Now clear exactly one bit in leaf[ci].
             */
            for (;;) {
                uint64_t lv = atomic_load(&tree->leaves[ci]);
                if (lv == 0) {
                    /*
                     * Transient inconsistency.  Re-increment and retry
                     * a different subtree.
                     */
                    atomic_fetch_add(&tree->root, addend[ci]);
                    expected = atomic_load(&tree->root);
                    goto retry_root;
                }

                int bit = select_bit(lv, bias);
                uint64_t bm = 1ULL << bit;
                uint64_t old = atomic_fetch_and(&tree->leaves[ci], ~bm);
                if (old & bm) {
                    /* Cleared the bit — success. */
                    return (st_select_result_t){
                        (uint64_t)(ci * ST_LEAF_CAPACITY + bit),
                        desired == 0
                    };
                }
                /* Bit was already cleared by a concurrent select. Retry. */
            }
        }
        /* CAS failed — expected has been updated. Retry. */
    retry_root:;
    }

    return (st_select_result_t){ ST_INVALID_INDEX, false };
}

bool signal_tree_empty(const signal_tree_t *tree)
{
    return atomic_load(&tree->root) == 0;
}
