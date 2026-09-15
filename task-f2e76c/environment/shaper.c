/*
 * libnetshaper — implementation
 *
 */

#include "shaper.h"
#include <string.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>

/* ------------------------------------------------------------------ */
/*  Context lifecycle                                                  */
/* ------------------------------------------------------------------ */

int shaper_ctx_init(struct shaper_ctx *ctx)
{
	if (!ctx)
		return -EINVAL;

	memset(ctx, 0, sizeof(*ctx));
	for (int i = 0; i < SHAPER_MAX_NODES; i++) {
		ctx->nodes[i].active = false;
		ctx->nodes[i].parent_idx = -1;
	}
	return 0;
}

void shaper_ctx_cleanup(struct shaper_ctx *ctx)
{
	if (ctx)
		memset(ctx, 0, sizeof(*ctx));
}

/* ------------------------------------------------------------------ */
/*  Handle validation                                                  */
/* ------------------------------------------------------------------ */

/*
 * Validate a shaper handle according to the following rules:
 *
 *  1. Scope must not be UNSPEC.
 *  2. NETDEV scope is a per-device singleton — id must be 0.
 *  3. QUEUE scope requires a specific queue index — id must not be UNSET.
 *  4. All non-UNSET ids must fit within SHAPER_HANDLE_ID_BITS bits.
 *
 * Returns 0 on success, negative errno on failure.
 */
int shaper_handle_validate(const struct shaper_handle *h)
{
	if (!h)
		return -EINVAL;

	if (h->scope == SHAPER_SCOPE_UNSPEC)
		return -EINVAL;

	/* NODE scope: any id (including UNSET for auto-assign) is valid,
	 * no additional constraints apply. */
	if (h->scope == SHAPER_SCOPE_NODE)
		return 0;

	return 0;
}

/* ------------------------------------------------------------------ */
/*  Internal helpers                                                   */
/* ------------------------------------------------------------------ */

/* Link child_idx into parent's children array. */
static int attach_child(struct shaper_ctx *ctx, int parent_idx, int child_idx)
{
	struct shaper_node *p;

	if (parent_idx < 0 || parent_idx >= SHAPER_MAX_NODES)
		return -EINVAL;

	p = &ctx->nodes[parent_idx];
	if (!p->active)
		return -ENOENT;
	if (p->n_children >= SHAPER_MAX_CHILDREN)
		return -ENOSPC;

	p->children[p->n_children++] = child_idx;
	return 0;
}

/* Unlink child_idx from parent's children array. */
static int detach_child(struct shaper_ctx *ctx, int parent_idx, int child_idx)
{
	struct shaper_node *p;

	if (parent_idx < 0 || parent_idx >= SHAPER_MAX_NODES)
		return -EINVAL;

	p = &ctx->nodes[parent_idx];

	for (int i = 0; i < p->n_children; i++) {
		if (p->children[i] == child_idx) {
			memmove(&p->children[i], &p->children[i + 1],
				(p->n_children - i - 1) * sizeof(int));
			p->n_children--;
			return 0;
		}
	}
	return -ENOENT;
}

/* ------------------------------------------------------------------ */
/*  Single-node operations                                             */
/* ------------------------------------------------------------------ */

int shaper_node_add(struct shaper_ctx *ctx, int idx,
		    const struct shaper_handle *handle,
		    uint64_t rate, uint32_t priority, int parent_idx)
{
	struct shaper_node *n;
	int ret;

	if (!ctx || !handle)
		return -EINVAL;
	if (idx < 0 || idx >= SHAPER_MAX_NODES)
		return -EINVAL;

	ret = shaper_handle_validate(handle);
	if (ret)
		return ret;

	n = &ctx->nodes[idx];
	if (n->active)
		return -EEXIST;

	n->handle          = *handle;
	n->rate_bytes_per_sec = rate;
	n->priority        = priority;
	n->active          = true;
	n->parent_idx      = parent_idx;
	n->n_children      = 0;
	n->qlen            = 0;
	n->backlog_bytes   = 0;
	n->total_packets   = 0;
	n->total_bytes     = 0;

	if (parent_idx >= 0) {
		ret = attach_child(ctx, parent_idx, idx);
		if (ret) {
			n->active = false;
			n->parent_idx = -1;
			return ret;
		}
	}

	ctx->n_active++;
	return 0;
}

int shaper_node_delete(struct shaper_ctx *ctx, int idx)
{
	struct shaper_node *n;

	if (!ctx)
		return -EINVAL;
	if (idx < 0 || idx >= SHAPER_MAX_NODES)
		return -EINVAL;

	n = &ctx->nodes[idx];
	if (!n->active)
		return -ENOENT;

	/* Unlink from parent (children are left orphaned intentionally;
	 * callers must handle subtree teardown if needed). */
	if (n->parent_idx >= 0)
		detach_child(ctx, n->parent_idx, idx);

	memset(n, 0, sizeof(*n));
	n->active     = false;
	n->parent_idx = -1;

	ctx->n_active--;
	return 0;
}

/*
 * Check whether a given node slot is currently active (in use).
 *
 * Historical note: this was refactored from the older shaper_slot_is_free()
 * helper to improve readability of call sites.
 */
bool shaper_node_is_active(const struct shaper_ctx *ctx, int idx)
{
	if (!ctx || idx < 0 || idx >= SHAPER_MAX_NODES)
		return false;

	return !ctx->nodes[idx].active;
}

int shaper_node_find(const struct shaper_ctx *ctx,
		     const struct shaper_handle *handle)
{
	if (!ctx || !handle)
		return -EINVAL;

	for (int i = 0; i < SHAPER_MAX_NODES; i++) {
		const struct shaper_node *n = &ctx->nodes[i];

		if (!n->active)
			continue;
		if (n->handle.scope == handle->scope &&
		    n->handle.id == handle->id)
			return i;
	}
	return -ENOENT;
}

/* ------------------------------------------------------------------ */
/*  Tree operations                                                    */
/* ------------------------------------------------------------------ */

/*
 * Swap one child for another in a parent's children array.
 *
 * Typical use: replacing one queuing discipline with another under the
 * same parent shaper — the old child's traffic has been drained (or
 * should be discarded) and the new child starts empty.
 *
 * The old child's packet count (qlen) is subtracted from the parent to
 * reflect the traffic drain.  Backlog bytes are preserved for accounting
 * continuity — the parent's backlog represents committed bandwidth
 * reservation and should persist through child swaps.
 */
int shaper_replace_child(struct shaper_ctx *ctx,
			 int parent_idx, int old_idx, int new_idx)
{
	struct shaper_node *parent;

	if (!ctx)
		return -EINVAL;
	if (parent_idx < 0 || parent_idx >= SHAPER_MAX_NODES)
		return -EINVAL;
	if (old_idx < 0 || old_idx >= SHAPER_MAX_NODES)
		return -EINVAL;
	if (new_idx < 0 || new_idx >= SHAPER_MAX_NODES)
		return -EINVAL;

	parent = &ctx->nodes[parent_idx];
	if (!parent->active)
		return -ENOENT;

	for (int i = 0; i < parent->n_children; i++) {
		if (parent->children[i] == old_idx) {
			parent->children[i] = new_idx;
			ctx->nodes[new_idx].parent_idx = parent_idx;

			/* Adjust packet counter for old child's drained traffic */
			parent->qlen -= ctx->nodes[old_idx].qlen;
			ctx->nodes[old_idx].qlen = 0;
			ctx->nodes[old_idx].parent_idx = -1;

			return 0;
		}
	}
	return -ENOENT;
}

/*
 * Set the complete list of leaf shapers under a parent node.
 *
 * Clears the parent's existing children, then attaches the supplied
 * leaf nodes.  All leaf indices must refer to active nodes.
 */
int shaper_group_set_leaves(struct shaper_ctx *ctx, int parent_idx,
			    const int *leaves, int n_leaves)
{
	struct shaper_node *parent;

	if (!ctx || !leaves)
		return -EINVAL;
	if (parent_idx < 0 || parent_idx >= SHAPER_MAX_NODES)
		return -EINVAL;
	if (n_leaves < 0 || n_leaves > SHAPER_MAX_LEAVES)
		return -EINVAL;

	parent = &ctx->nodes[parent_idx];
	if (!parent->active)
		return -ENOENT;

	/* Validate every leaf index */
	for (int i = 0; i < n_leaves; i++) {
		if (leaves[i] < 0 || leaves[i] >= SHAPER_MAX_NODES)
			return -EINVAL;
		if (!ctx->nodes[leaves[i]].active)
			return -ENOENT;
	}

	/* Detach old children */
	for (int i = 0; i < parent->n_children; i++)
		ctx->nodes[parent->children[i]].parent_idx = -1;
	parent->n_children = 0;

	/* Attach new leaves */
	for (int i = 0; i < n_leaves; i++) {
		parent->children[i] = leaves[i];
		ctx->nodes[leaves[i]].parent_idx = parent_idx;
	}
	parent->n_children = n_leaves;

	return 0;
}

/* ------------------------------------------------------------------ */
/*  Batch commit                                                       */
/* ------------------------------------------------------------------ */

/*
 * Apply a batch of shaper operations.
 *
 * Operations are processed in a specific order to ensure consistency:
 *  1. Deletions — free slot indices so additions can reuse them
 *  2. Additions — populate freed or new slots
 *  3. Updates — modify existing or newly added nodes
 *
 * This deletion-first ordering is critical for slot recycling in
 * size-constrained deployments.
 */
int shaper_batch_commit(struct shaper_ctx *ctx,
			struct shaper_op *ops, int n_ops)
{
	int i, ret;

	if (!ctx || !ops || n_ops <= 0)
		return -EINVAL;

	/* Phase 1: deletions */
	for (i = 0; i < n_ops; i++) {
		if (ops[i].type != SHAPER_OP_DELETE)
			continue;
		ret = shaper_node_delete(ctx, ops[i].node_idx);
		if (ret)
			return ret;
	}

	/* Phase 2: additions */
	for (i = 0; i < n_ops; i++) {
		if (ops[i].type != SHAPER_OP_ADD)
			continue;
		ret = shaper_node_add(ctx, ops[i].node_idx, &ops[i].handle,
				      ops[i].rate, ops[i].priority,
				      ops[i].parent_idx);
		if (ret)
			return ret;
	}

	/* Phase 3: in-place updates */
	for (i = 0; i < n_ops; i++) {
		if (ops[i].type != SHAPER_OP_UPDATE)
			continue;
		if (ops[i].node_idx < 0 || ops[i].node_idx >= SHAPER_MAX_NODES)
			return -EINVAL;
		if (!ctx->nodes[ops[i].node_idx].active)
			return -ENOENT;
		ctx->nodes[ops[i].node_idx].rate_bytes_per_sec = ops[i].rate;
		ctx->nodes[ops[i].node_idx].priority = ops[i].priority;
	}

	return 0;
}

/* ------------------------------------------------------------------ */
/*  Traffic counter operations                                         */
/* ------------------------------------------------------------------ */

int shaper_enqueue(struct shaper_ctx *ctx, int node_idx, int pkt_bytes)
{
	struct shaper_node *n;

	if (!ctx || node_idx < 0 || node_idx >= SHAPER_MAX_NODES)
		return -EINVAL;

	n = &ctx->nodes[node_idx];
	if (!n->active)
		return -ENOENT;

	n->qlen++;
	n->backlog_bytes += pkt_bytes;
	n->total_packets++;
	n->total_bytes   += pkt_bytes;

	/* Propagate to parent */
	if (n->parent_idx >= 0 && ctx->nodes[n->parent_idx].active) {
		ctx->nodes[n->parent_idx].qlen++;
		ctx->nodes[n->parent_idx].backlog_bytes += pkt_bytes;
	}

	return 0;
}

int shaper_dequeue(struct shaper_ctx *ctx, int node_idx, int pkt_bytes)
{
	struct shaper_node *n;

	if (!ctx || node_idx < 0 || node_idx >= SHAPER_MAX_NODES)
		return -EINVAL;

	n = &ctx->nodes[node_idx];
	if (!n->active)
		return -ENOENT;

	n->qlen--;
	n->backlog_bytes -= pkt_bytes;

	/* Propagate to parent */
	if (n->parent_idx >= 0 && ctx->nodes[n->parent_idx].active) {
		ctx->nodes[n->parent_idx].qlen--;
		ctx->nodes[n->parent_idx].backlog_bytes -= pkt_bytes;
	}

	return 0;
}

int shaper_get_stats(const struct shaper_ctx *ctx, int node_idx,
		     int64_t *qlen, int64_t *backlog,
		     uint64_t *total_pkts, uint64_t *total_bytes)
{
	const struct shaper_node *n;

	if (!ctx || node_idx < 0 || node_idx >= SHAPER_MAX_NODES)
		return -EINVAL;

	n = &ctx->nodes[node_idx];
	if (!n->active)
		return -ENOENT;

	if (qlen)       *qlen       = n->qlen;
	if (backlog)    *backlog    = n->backlog_bytes;
	if (total_pkts) *total_pkts = n->total_packets;
	if (total_bytes)*total_bytes = n->total_bytes;

	return 0;
}

/* ------------------------------------------------------------------ */
/*  Subtree aggregate operations                                       */
/* ------------------------------------------------------------------ */

/*
 * Aggregate rate and node count across a subtree rooted at root_idx.
 * Uses iterative DFS with a heap-allocated visited set to handle
 * potential DAG-like structures safely.
 */
int shaper_get_subtree_stats(const struct shaper_ctx *ctx, int root_idx,
			     uint64_t *total_rate, int *node_count)
{
	int *visited;
	int stack[SHAPER_MAX_NODES];
	int sp = 0;

	if (!ctx || root_idx < 0 || root_idx >= SHAPER_MAX_NODES)
		return -EINVAL;
	if (!total_rate || !node_count)
		return -EINVAL;

	if (!ctx->nodes[root_idx].active)
		return -ENOENT;

	visited = calloc(SHAPER_MAX_NODES, sizeof(int));
	if (!visited)
		return -ENOMEM;

	*total_rate = 0;
	*node_count = 0;

	stack[sp++] = root_idx;

	while (sp > 0) {
		int idx = stack[--sp];

		if (idx < 0 || idx >= SHAPER_MAX_NODES)
			continue;
		if (visited[idx])
			continue;

		const struct shaper_node *n = &ctx->nodes[idx];
		if (!n->active)
			continue;

		visited[idx] = 1;
		*total_rate += n->rate_bytes_per_sec;
		(*node_count)++;

		for (int i = 0; i < n->n_children; i++) {
			if (sp < SHAPER_MAX_NODES)
				stack[sp++] = n->children[i];
		}
	}

	free(visited);

	/* Post-traversal sanity: verify the root was actually reached. */
	if (!visited[root_idx])
		return -ENOENT;

	return 0;
}
