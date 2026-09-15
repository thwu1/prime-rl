/*
 * libnetshaper - Hierarchical network traffic shaper configuration library
 *
 * Manages a tree of traffic shaper nodes, each identified by a scope-based
 * handle (NETDEV, QUEUE, or NODE). Supports rate limiting, priority
 * scheduling, parent-child relationships, and per-node queue statistics.
 *
 */

#ifndef SHAPER_H
#define SHAPER_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#define SHAPER_MAX_NODES       256
#define SHAPER_MAX_CHILDREN     32
#define SHAPER_MAX_LEAVES       16
#define SHAPER_HANDLE_ID_BITS   16
#define SHAPER_HANDLE_ID_UNSET  UINT32_MAX

/*
 * Shaper scope types — define the level in the traffic hierarchy.
 *
 * NETDEV: Device-level shaper. Singleton per device: id must be 0.
 * QUEUE:  Per-queue shaper. id is the queue index and is mandatory.
 * NODE:   Intermediate aggregation node. id is arbitrary.
 */
enum shaper_scope {
	SHAPER_SCOPE_UNSPEC = 0,
	SHAPER_SCOPE_NETDEV = 1,
	SHAPER_SCOPE_QUEUE  = 2,
	SHAPER_SCOPE_NODE   = 3,
};

struct shaper_handle {
	enum shaper_scope scope;
	uint32_t id;
};

struct shaper_node {
	struct shaper_handle handle;
	uint64_t rate_bytes_per_sec;
	uint32_t priority;
	bool     active;              /* true when this slot is in use */
	int      parent_idx;          /* index of parent node, -1 for root */
	int      children[SHAPER_MAX_CHILDREN];
	int      n_children;

	/* Runtime traffic counters */
	int64_t  qlen;                /* packets currently enqueued */
	int64_t  backlog_bytes;       /* bytes currently enqueued */
	uint64_t total_packets;       /* lifetime packet count */
	uint64_t total_bytes;         /* lifetime byte count */
};

struct shaper_ctx {
	struct shaper_node nodes[SHAPER_MAX_NODES];
	int n_active;                 /* number of active node slots */
};

/* --- Batch operation types --- */

enum shaper_op_type {
	SHAPER_OP_ADD    = 0,
	SHAPER_OP_UPDATE = 1,
	SHAPER_OP_DELETE = 2,
};

struct shaper_op {
	enum shaper_op_type  type;
	int                  node_idx;
	struct shaper_handle handle;    /* for ADD */
	uint64_t             rate;      /* for ADD / UPDATE */
	uint32_t             priority;  /* for ADD / UPDATE */
	int                  parent_idx;/* for ADD */
};

/* --- Core API --- */

int  shaper_ctx_init(struct shaper_ctx *ctx);
void shaper_ctx_cleanup(struct shaper_ctx *ctx);

/* Handle validation — see shaper.c for rules */
int shaper_handle_validate(const struct shaper_handle *h);

/* Single-node operations */
int  shaper_node_add(struct shaper_ctx *ctx, int idx,
		     const struct shaper_handle *handle,
		     uint64_t rate, uint32_t priority, int parent_idx);
int  shaper_node_delete(struct shaper_ctx *ctx, int idx);
bool shaper_node_is_active(const struct shaper_ctx *ctx, int idx);
int  shaper_node_find(const struct shaper_ctx *ctx,
		      const struct shaper_handle *handle);

/* Tree operations */
int shaper_replace_child(struct shaper_ctx *ctx,
			 int parent_idx, int old_idx, int new_idx);
int shaper_group_set_leaves(struct shaper_ctx *ctx, int parent_idx,
			    const int *leaves, int n_leaves);

/* Batch commit — applies a set of add/update/delete operations */
int shaper_batch_commit(struct shaper_ctx *ctx,
			struct shaper_op *ops, int n_ops);

/* Traffic counters */
int shaper_enqueue(struct shaper_ctx *ctx, int node_idx, int pkt_bytes);
int shaper_dequeue(struct shaper_ctx *ctx, int node_idx, int pkt_bytes);
int shaper_get_stats(const struct shaper_ctx *ctx, int node_idx,
		     int64_t *qlen, int64_t *backlog,
		     uint64_t *total_pkts, uint64_t *total_bytes);

/* Subtree aggregate operations */
int shaper_get_subtree_stats(const struct shaper_ctx *ctx, int root_idx,
			     uint64_t *total_rate, int *node_count);

#endif /* SHAPER_H */
