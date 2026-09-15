# Hierarchical Network Traffic Shaper — Specification

## Architecture

The shaper manages a tree of nodes representing bandwidth allocations.
Each node has a **scope** and a **handle** (32-bit encoded identifier).

### Scopes

| Scope   | Value | Role                        | Constraints                       |
|---------|-------|-----------------------------|-----------------------------------|
| NETDEV  | 1     | Root of the shaper tree     | Exactly one instance; id MUST = 0 |
| QUEUE   | 2     | Leaf (hardware TX queue)    | id MUST be > 0                    |
| GROUP   | 3     | Interior aggregate node     | Created via `shaper_group()`      |

### Handle encoding

```
handle = (scope << 30) | id
```

- Bottom 30 bits: **id** (valid range: 0 to 2^30 − 1 inclusive).
- Top 2 bits: **scope**.
- IDs exceeding `SHAPER_HANDLE_ID_MAX` (= 2^30 − 1) **MUST** be rejected.

---

## Operations

### `shaper_node_create(ctx, scope, id, rate, burst, parent_idx)`

Creates a new shaper node.  Returns the node index (≥ 0) on success,
or a negative errno on failure.

**Validation rules (checked before any mutation):**

1. `scope` must be NETDEV, QUEUE, or GROUP.
2. QUEUE scope: `id` must be > 0.  (id = 0 is reserved and invalid.)
3. NETDEV scope: `id` must be 0 **and** no other NETDEV node may exist.
4. `id` must not exceed `SHAPER_HANDLE_ID_MAX`.
5. The resulting handle must not match any **active** (used) node.
6. Non-NETDEV nodes require a valid, active parent of NETDEV or GROUP scope.

### `shaper_node_delete(ctx, node_idx)`

Removes a node.  Fails with `-EBUSY` if the node has children.

### `shaper_node_modify(ctx, node_idx, rate, burst)`

Updates bandwidth parameters of an existing active node.

### `shaper_find_by_handle(ctx, handle)`

Returns the index of the **active** node with the given handle,
or negative errno if not found.

### `shaper_group(ctx, parent_idx, leaf_handles, n_leaves, rate, burst, result_statuses, results_size)`

Creates a new GROUP node under `parent_idx` and reparents the given
leaf nodes under it.  Returns the group node index on success.

**Validation rules:**

1. `n_leaves` must be in `[1, MAX_CHILDREN]`.
2. `results_size` must be ≥ `n_leaves` (one status slot per leaf).
3. All entries in `leaf_handles` must be **unique** — duplicates are rejected.
4. Every leaf handle must resolve to an active node.

---

## `shaper_rebalance(ctx, subtree_root_idx)`

Enforces the constraint that the sum of a node's children's rates must
not exceed the node's own rate.  Operates on the subtree rooted at
`subtree_root_idx`.

**Traversal order:** depth-first, post-order — each child's subtree is
fully rebalanced before the parent node is considered.

At each interior node (NETDEV or GROUP) with one or more children:

1. Let `total` = sum of all children's `rate_bps`.
2. If `total` is 0 **or** `total ≤ node->rate_bps`, no adjustment is needed.
3. Otherwise the node is overcommitted and children must be scaled down.

**Scaling properties (when overcommitted):**

- **Proportionality**: Each child's new rate is proportional to its original
  rate relative to the children's total.  Use integer floor division — no
  floating-point arithmetic.
- **Maximum utilization**: After scaling, the difference between the parent's
  rate and the sum of all children's new rates must be strictly less than
  the number of children whose new rate is positive.
- **Remainder distribution**: Any shortfall from floor division is made up by
  adding exactly 1 bps to selected children.  Only children whose
  post-scaling rate is positive are eligible.  Each eligible child receives
  at most 1 unit.  Distribution follows a deterministic, stable ordering.
- **Zero preservation**: A child with `rate_bps = 0` always produces a new
  rate of 0 and is never eligible for remainder bandwidth.

**Edge cases:**

- If all children have rate 0, `total` is 0 and no scaling occurs.
- Leaf nodes (no children) require no action when passed as `subtree_root_idx`.
- Returns 0 on success.  Returns `-EINVAL` if `subtree_root_idx` is out of
  range or refers to an inactive node.

---

## `shaper_compact(ctx)`

Defragments the node array by closing gaps left by deleted nodes.
All active nodes are relocated to consecutive indices starting at 0,
preserving their relative order.

**Invariants:**

1. The relative index order of active nodes is preserved — a node at a
   lower original index occupies a lower compacted index.
2. All handles are preserved: the same handle resolves to the same
   logical node via `shaper_find_by_handle()`.
3. **All** parent-child cross-references are updated to reflect new
   positions — every `parent_idx` and every entry in every `children[]`
   array must use the new indices.
4. `ctx->count` is set to the number of active nodes (the new high-water
   mark).
5. Slots beyond the new count are inactive.

**Returns:** the number of active nodes (new `ctx->count`) on success.

**Note:** After compaction, previously returned node indices are
invalidated.  Use `shaper_find_by_handle()` to locate nodes.

---

## `shaper_validate_tree(ctx)`

Checks structural integrity of the shaper tree.  Returns 0 if valid,
negative error code otherwise.

**Checks performed:**

1. Root nodes (`parent_idx < 0`) must have NETDEV scope.
2. At most one root node exists.
3. Every active node's parent (if any) must itself be active.
4. Children are active, and each child's `parent_idx` points back to the parent.

GROUP nodes may have **any positive number** of children (including exactly 1).
A GROUP node is **not invalid** merely because it has fewer than 2 children.

---

## Internal: `handle_exists(ctx, handle)`

Returns 1 if an **active** (used = 1) node with the given handle exists
in the context, 0 otherwise.  Must inspect the `used` field — not its
inverse.
