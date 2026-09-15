#pragma once

#include "avl.h"
#include "hashtable.h"


struct ZSet {
    AVLNode *root = NULL;   // index by (score, name)
    HMap hmap;              // index by name
};

struct ZNode {
    AVLNode tree;
    HNode   hmap;
    double  score = 0;
    size_t  len = 0;
    char    name[0];        // flexible array
};

// Insert a new (name, score) pair, or update the score if name already exists.
// Returns true if a new entry was created, false if an existing entry was updated.
bool   zset_insert(ZSet *zset, const char *name, size_t len, double score);

// Look up a member by name. Returns NULL if not found.
ZNode *zset_lookup(ZSet *zset, const char *name, size_t len);

// Delete a node (must exist in the zset). Removes from both indices and frees memory.
void   zset_delete(ZSet *zset, ZNode *node);

// Find the first node whose (score, name) >= the given (score, name).
// Returns NULL if no such node exists.
ZNode *zset_seekge(ZSet *zset, double score, const char *name, size_t len);

// Destroy all nodes in the zset, freeing memory.
void   zset_clear(ZSet *zset);

// Navigate to the node at rank offset relative to the given node.
// Returns NULL if offset goes out of bounds or node is NULL.
ZNode *znode_offset(ZNode *node, int64_t offset);
