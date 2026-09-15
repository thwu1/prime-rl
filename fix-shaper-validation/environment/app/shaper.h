/*
 * Hierarchical Network Traffic Shaper — Library Header
 *
 * Manages a tree of shaper nodes for bandwidth allocation.
 * Nodes have three scopes: NETDEV (root), QUEUE (leaf), GROUP (interior).
 *
 */

#ifndef SHAPER_H
#define SHAPER_H

#include <stdint.h>

/* Scope values */
#define SHAPER_SCOPE_UNSPEC   0
#define SHAPER_SCOPE_NETDEV   1  /* Root scope */
#define SHAPER_SCOPE_QUEUE    2  /* Leaf scope */
#define SHAPER_SCOPE_GROUP    3  /* Interior aggregate scope */

/*
 * Handle encoding: top 2 bits = scope, bottom 30 bits = id.
 *   handle = (scope << 30) | id
 */
#define SHAPER_HANDLE_ID_BITS     30
#define SHAPER_HANDLE_ID_MAX      ((1U << SHAPER_HANDLE_ID_BITS) - 1)

#define SHAPER_MAKE_HANDLE(scope, id)  \
    (((uint32_t)(scope) << SHAPER_HANDLE_ID_BITS) | \
     ((uint32_t)(id) & SHAPER_HANDLE_ID_MAX))

#define SHAPER_HANDLE_SCOPE(h)  ((h) >> SHAPER_HANDLE_ID_BITS)
#define SHAPER_HANDLE_ID(h)     ((h) & SHAPER_HANDLE_ID_MAX)

#define MAX_NODES      256
#define MAX_CHILDREN    64

struct shaper_node {
    uint32_t handle;
    int      used;          /* 1 = slot active, 0 = slot free */
    int      parent_idx;    /* index into nodes[], -1 for root */
    int      child_count;
    int      children[MAX_CHILDREN];
    uint64_t rate_bps;
    uint64_t burst_bytes;
};

struct shaper_ctx {
    struct shaper_node nodes[MAX_NODES];
    int count;              /* high-water mark of allocated indices */
};

/* Lifecycle */
struct shaper_ctx *shaper_ctx_new(void);
void               shaper_ctx_free(struct shaper_ctx *ctx);
void               shaper_ctx_init(struct shaper_ctx *ctx);

/* Node operations */
int shaper_node_create(struct shaper_ctx *ctx, int scope, uint32_t id,
                       uint64_t rate_bps, uint64_t burst_bytes,
                       int parent_idx);
int shaper_node_delete(struct shaper_ctx *ctx, int node_idx);
int shaper_node_modify(struct shaper_ctx *ctx, int node_idx,
                       uint64_t rate_bps, uint64_t burst_bytes);

/* Lookup */
int shaper_find_by_handle(struct shaper_ctx *ctx, uint32_t handle);

/* Group operation: create a GROUP node and reparent leaves under it */
int shaper_group(struct shaper_ctx *ctx, int parent_idx,
                 uint32_t *leaf_handles, int n_leaves,
                 uint64_t group_rate, uint64_t group_burst,
                 int *result_statuses, int results_size);

/* Hierarchical rate rebalancing */
int shaper_rebalance(struct shaper_ctx *ctx, int subtree_root);

/* Node array compaction */
int shaper_compact(struct shaper_ctx *ctx);

/* Accessor helpers (for FFI / testing) */
uint32_t shaper_get_handle(struct shaper_ctx *ctx, int idx);
int      shaper_get_used(struct shaper_ctx *ctx, int idx);
int      shaper_get_parent(struct shaper_ctx *ctx, int idx);
int      shaper_get_child_count(struct shaper_ctx *ctx, int idx);
uint64_t shaper_get_rate(struct shaper_ctx *ctx, int idx);

/* Tree integrity check */
int shaper_validate_tree(struct shaper_ctx *ctx);

#endif /* SHAPER_H */
