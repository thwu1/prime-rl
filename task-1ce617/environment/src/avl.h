#pragma once

#include <stddef.h>
#include <stdint.h>


struct AVLNode {
    AVLNode *parent = NULL;
    AVLNode *left = NULL;
    AVLNode *right = NULL;
    uint32_t height = 0;    // subtree height
    uint32_t cnt = 0;       // subtree size
};

inline void avl_init(AVLNode *node) {
    node->left = node->right = node->parent = NULL;
    node->height = 1;
    node->cnt = 1;
}

// helpers
inline uint32_t avl_height(AVLNode *node) { return node ? node->height : 0; }
inline uint32_t avl_cnt(AVLNode *node) { return node ? node->cnt : 0; }

// Fix the tree after insertion or deletion.
// Walks up from `node` to the root, rebalancing at each ancestor.
// Returns the (possibly new) root of the tree.
AVLNode *avl_fix(AVLNode *node);

// Delete `node` from the tree.
// Returns the (possibly new) root.
// If the node has two children, it is swapped with its in-order successor.
AVLNode *avl_del(AVLNode *node);

// Navigate to the node at rank `offset` relative to `node`.
// offset > 0 moves toward successors, offset < 0 toward predecessors.
// Must run in O(log N) using the `cnt` fields.
// Returns NULL if the offset goes out of bounds.
AVLNode *avl_offset(AVLNode *node, int64_t offset);
