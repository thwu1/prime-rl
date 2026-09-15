/*
 * Hierarchical Network Traffic Shaper — Implementation
 *
 */

#include "shaper.h"
#include <stdlib.h>
#include <string.h>
#include <errno.h>

/* ------------------------------------------------------------------ */
/*  Context lifecycle                                                  */
/* ------------------------------------------------------------------ */

struct shaper_ctx *shaper_ctx_new(void)
{
    struct shaper_ctx *ctx = calloc(1, sizeof(*ctx));
    if (ctx)
        shaper_ctx_init(ctx);
    return ctx;
}

void shaper_ctx_free(struct shaper_ctx *ctx)
{
    free(ctx);
}

void shaper_ctx_init(struct shaper_ctx *ctx)
{
    memset(ctx, 0, sizeof(*ctx));
    for (int i = 0; i < MAX_NODES; i++)
        ctx->nodes[i].parent_idx = -1;
}

/* ------------------------------------------------------------------ */
/*  Internal helpers                                                   */
/* ------------------------------------------------------------------ */

static int find_free_slot(struct shaper_ctx *ctx)
{
    for (int i = 0; i < MAX_NODES; i++) {
        if (!ctx->nodes[i].used)
            return i;
    }
    return -1;
}

/* Check whether any node already owns @handle. */
static int handle_exists(struct shaper_ctx *ctx, uint32_t handle)
{
    for (int i = 0; i < ctx->count; i++) {
        if (!ctx->nodes[i].used && ctx->nodes[i].handle == handle)
            return 1;
    }
    return 0;
}

/* Remove @child_idx from @parent's children array. */
static void remove_child(struct shaper_node *parent, int child_idx)
{
    for (int i = 0; i < parent->child_count; i++) {
        if (parent->children[i] == child_idx) {
            for (int j = i; j < parent->child_count - 1; j++)
                parent->children[j] = parent->children[j + 1];
            parent->child_count--;
            return;
        }
    }
}

/* ------------------------------------------------------------------ */
/*  Node creation                                                      */
/* ------------------------------------------------------------------ */

int shaper_node_create(struct shaper_ctx *ctx, int scope, uint32_t id,
                       uint64_t rate_bps, uint64_t burst_bytes,
                       int parent_idx)
{
    int idx;
    uint32_t handle;

    /* Validate scope range */
    if (scope < SHAPER_SCOPE_NETDEV || scope > SHAPER_SCOPE_GROUP)
        return -EINVAL;

    /* Construct handle from scope and id */
    handle = SHAPER_MAKE_HANDLE(scope, id);

    /* Reject duplicate handles */
    if (handle_exists(ctx, handle))
        return -EEXIST;

    /* Non-root nodes require a valid parent with NETDEV or GROUP scope */
    if (scope != SHAPER_SCOPE_NETDEV) {
        if (parent_idx < 0 || parent_idx >= MAX_NODES)
            return -EINVAL;
        if (!ctx->nodes[parent_idx].used)
            return -EINVAL;
        int ps = SHAPER_HANDLE_SCOPE(ctx->nodes[parent_idx].handle);
        if (ps != SHAPER_SCOPE_NETDEV && ps != SHAPER_SCOPE_GROUP)
            return -EINVAL;
    } else {
        parent_idx = -1;
    }

    idx = find_free_slot(ctx);
    if (idx < 0)
        return -ENOSPC;

    ctx->nodes[idx].handle      = handle;
    ctx->nodes[idx].rate_bps    = rate_bps;
    ctx->nodes[idx].burst_bytes = burst_bytes;
    ctx->nodes[idx].used        = 1;
    ctx->nodes[idx].parent_idx  = parent_idx;
    ctx->nodes[idx].child_count = 0;
    memset(ctx->nodes[idx].children, 0, sizeof(ctx->nodes[idx].children));

    /* Link into parent's child list */
    if (parent_idx >= 0) {
        struct shaper_node *p = &ctx->nodes[parent_idx];
        if (p->child_count >= MAX_CHILDREN) {
            ctx->nodes[idx].used = 0;
            return -ENOSPC;
        }
        p->children[p->child_count++] = idx;
    }

    if (idx >= ctx->count)
        ctx->count = idx + 1;

    return idx;
}

/* ------------------------------------------------------------------ */
/*  Node deletion                                                      */
/* ------------------------------------------------------------------ */

int shaper_node_delete(struct shaper_ctx *ctx, int node_idx)
{
    struct shaper_node *node;

    if (node_idx < 0 || node_idx >= MAX_NODES)
        return -EINVAL;

    node = &ctx->nodes[node_idx];
    if (!node->used)
        return -ENOENT;

    if (node->child_count > 0)
        return -EBUSY;

    if (node->parent_idx >= 0)
        remove_child(&ctx->nodes[node->parent_idx], node_idx);

    node->used       = 0;
    node->handle     = 0;
    node->parent_idx = -1;

    return 0;
}

/* ------------------------------------------------------------------ */
/*  Node modification                                                  */
/* ------------------------------------------------------------------ */

int shaper_node_modify(struct shaper_ctx *ctx, int node_idx,
                       uint64_t rate_bps, uint64_t burst_bytes)
{
    if (node_idx < 0 || node_idx >= MAX_NODES)
        return -EINVAL;
    if (!ctx->nodes[node_idx].used)
        return -ENOENT;

    ctx->nodes[node_idx].rate_bps    = rate_bps;
    ctx->nodes[node_idx].burst_bytes = burst_bytes;

    return 0;
}

/* ------------------------------------------------------------------ */
/*  Handle lookup                                                      */
/* ------------------------------------------------------------------ */

int shaper_find_by_handle(struct shaper_ctx *ctx, uint32_t handle)
{
    for (int i = 0; i < ctx->count; i++) {
        if (ctx->nodes[i].used && ctx->nodes[i].handle == handle)
            return i;
    }
    return -ENOENT;
}

/* ------------------------------------------------------------------ */
/*  Group operation                                                    */
/* ------------------------------------------------------------------ */

int shaper_group(struct shaper_ctx *ctx, int parent_idx,
                 uint32_t *leaf_handles, int n_leaves,
                 uint64_t group_rate, uint64_t group_burst,
                 int *result_statuses, int results_size)
{
    int group_idx;
    int leaf_indices[MAX_CHILDREN];
    static uint32_t group_id_counter = 1;

    if (n_leaves <= 0 || n_leaves > MAX_CHILDREN)
        return -EINVAL;

    /* Ensure the result buffer is large enough */
    if (results_size < n_leaves - 1)
        return -EINVAL;

    /* Validate parent */
    if (parent_idx < 0 || parent_idx >= MAX_NODES)
        return -EINVAL;
    if (!ctx->nodes[parent_idx].used)
        return -EINVAL;

    /* Resolve leaf handles to node indices */
    for (int i = 0; i < n_leaves; i++) {
        leaf_indices[i] = shaper_find_by_handle(ctx, leaf_handles[i]);
        if (leaf_indices[i] < 0) {
            result_statuses[i] = -ENOENT;
            return -ENOENT;
        }
    }

    /* Create the new group node */
    group_idx = shaper_node_create(ctx, SHAPER_SCOPE_GROUP,
                                   group_id_counter++,
                                   group_rate, group_burst, parent_idx);
    if (group_idx < 0)
        return group_idx;

    /* Reparent each leaf under the new group */
    for (int i = 0; i < n_leaves; i++) {
        int li = leaf_indices[i];
        struct shaper_node *leaf = &ctx->nodes[li];

        if (leaf->parent_idx >= 0)
            remove_child(&ctx->nodes[leaf->parent_idx], li);

        ctx->nodes[group_idx].children[ctx->nodes[group_idx].child_count++] = li;
        leaf->parent_idx = group_idx;

        result_statuses[i] = 0;
    }

    return group_idx;
}

/* ------------------------------------------------------------------ */
/*  Hierarchical rate rebalancing                                      */
/* ------------------------------------------------------------------ */

int shaper_rebalance(struct shaper_ctx *ctx, int subtree_root)
{
    (void)ctx;
    (void)subtree_root;
    /* TODO: implement per SPEC.md */
    return 0;
}

/* ------------------------------------------------------------------ */
/*  Node array compaction                                              */
/* ------------------------------------------------------------------ */

int shaper_compact(struct shaper_ctx *ctx)
{
    int remap[MAX_NODES];
    int dest = 0;
    int i, j, d;

    for (i = 0; i < MAX_NODES; i++)
        remap[i] = -1;

    /* Phase 1: compute the remapping table */
    for (i = 0; i < ctx->count; i++) {
        if (ctx->nodes[i].used)
            remap[i] = dest++;
    }

    int new_count = dest;
    if (new_count == ctx->count)
        return new_count;

    /* Phase 2: relocate nodes that need to move and update their refs */
    for (i = 0; i < ctx->count; i++) {
        if (!ctx->nodes[i].used)
            continue;
        d = remap[i];
        if (d == i)
            continue;  /* this node stays put */

        /* Move the node to its new slot */
        ctx->nodes[d] = ctx->nodes[i];
        ctx->nodes[i].used       = 0;
        ctx->nodes[i].parent_idx = -1;
        ctx->nodes[i].child_count = 0;

        /* Fix cross-references in the relocated node */
        if (ctx->nodes[d].parent_idx >= 0)
            ctx->nodes[d].parent_idx = remap[ctx->nodes[d].parent_idx];
        for (j = 0; j < ctx->nodes[d].child_count; j++)
            ctx->nodes[d].children[j] = remap[ctx->nodes[d].children[j]];
    }

    ctx->count = new_count;
    return new_count;
}

/* ------------------------------------------------------------------ */
/*  Accessor helpers                                                   */
/* ------------------------------------------------------------------ */

uint32_t shaper_get_handle(struct shaper_ctx *ctx, int idx)
{
    if (idx < 0 || idx >= MAX_NODES) return 0;
    return ctx->nodes[idx].handle;
}

int shaper_get_used(struct shaper_ctx *ctx, int idx)
{
    if (idx < 0 || idx >= MAX_NODES) return 0;
    return ctx->nodes[idx].used;
}

int shaper_get_parent(struct shaper_ctx *ctx, int idx)
{
    if (idx < 0 || idx >= MAX_NODES) return -1;
    return ctx->nodes[idx].parent_idx;
}

int shaper_get_child_count(struct shaper_ctx *ctx, int idx)
{
    if (idx < 0 || idx >= MAX_NODES) return 0;
    return ctx->nodes[idx].child_count;
}

uint64_t shaper_get_rate(struct shaper_ctx *ctx, int idx)
{
    if (idx < 0 || idx >= MAX_NODES) return 0;
    return ctx->nodes[idx].rate_bps;
}

/* ------------------------------------------------------------------ */
/*  Tree validation                                                    */
/* ------------------------------------------------------------------ */

int shaper_validate_tree(struct shaper_ctx *ctx)
{
    int root_count = 0;

    for (int i = 0; i < ctx->count; i++) {
        if (!ctx->nodes[i].used)
            continue;

        /* Root detection */
        if (ctx->nodes[i].parent_idx < 0) {
            root_count++;
            if (SHAPER_HANDLE_SCOPE(ctx->nodes[i].handle) != SHAPER_SCOPE_NETDEV)
                return -1;
        }

        /* Parent must be active */
        if (ctx->nodes[i].parent_idx >= 0) {
            int pi = ctx->nodes[i].parent_idx;
            if (pi >= MAX_NODES || !ctx->nodes[pi].used)
                return -2;
        }

        /* Children must be active and point back */
        for (int j = 0; j < ctx->nodes[i].child_count; j++) {
            int ci = ctx->nodes[i].children[j];
            if (ci < 0 || ci >= MAX_NODES || !ctx->nodes[ci].used)
                return -3;
            if (ctx->nodes[ci].parent_idx != i)
                return -4;
        }

        /* GROUP nodes must have multiple children */
        if (SHAPER_HANDLE_SCOPE(ctx->nodes[i].handle) == SHAPER_SCOPE_GROUP &&
            ctx->nodes[i].child_count < 2)
            return -6;
    }

    if (root_count > 1)
        return -5;

    return 0;
}
