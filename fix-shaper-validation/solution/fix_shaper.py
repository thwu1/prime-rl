#!/usr/bin/env python3
"""
Apply targeted fixes to /app/shaper.c for all seven identified bugs,
and implement the shaper_rebalance() algorithm.

Bug 1: handle_exists checks !used (free slots) instead of used (active)
Bug 2: QUEUE scope allows id=0 (missing validation)
Bug 3: NETDEV scope not enforced as singleton with id=0
Bug 4: Handle IDs exceeding 30-bit max silently truncated
Bug 5: GROUP results_size check off-by-one (n_leaves-1 vs n_leaves)
Bug 6: GROUP does not detect duplicate leaf handles
Bug 7: validate_tree erroneously rejects single-child GROUP nodes

Design: Implement shaper_rebalance — post-order DFS with proportional
rate scaling and remainder distribution.

"""

import sys

with open('/app/shaper.c', 'r') as f:
    code = f.read()

original = code

# ── Bug 1: Fix handle_exists polarity ────────────────────────────────
# The function must check active (used) nodes, not free (!used) nodes.
old = 'if (!ctx->nodes[i].used && ctx->nodes[i].handle == handle)'
new = 'if (ctx->nodes[i].used && ctx->nodes[i].handle == handle)'
assert old in code, "Bug 1 target not found"
code = code.replace(old, new)

# ── Bug 5: Fix GROUP results_size off-by-one ─────────────────────────
old = 'if (results_size < n_leaves - 1)'
new = 'if (results_size < n_leaves)'
assert old in code, "Bug 5 target not found"
code = code.replace(old, new)

# ── Bugs 2, 3, 4: Add missing validation in shaper_node_create ──────
# Insert scope/id/range checks before handle construction.
old_block = (
    '    /* Construct handle from scope and id */\n'
    '    handle = SHAPER_MAKE_HANDLE(scope, id);'
)
new_block = (
    '    /* QUEUE scope requires id > 0 */\n'
    '    if (scope == SHAPER_SCOPE_QUEUE && id == 0)\n'
    '        return -EINVAL;\n'
    '\n'
    '    /* NETDEV scope must be singleton with id=0 */\n'
    '    if (scope == SHAPER_SCOPE_NETDEV) {\n'
    '        if (id != 0)\n'
    '            return -EINVAL;\n'
    '        for (int k = 0; k < MAX_NODES; k++) {\n'
    '            if (ctx->nodes[k].used &&\n'
    '                SHAPER_HANDLE_SCOPE(ctx->nodes[k].handle) == SHAPER_SCOPE_NETDEV)\n'
    '                return -EEXIST;\n'
    '        }\n'
    '    }\n'
    '\n'
    '    /* Reject IDs that exceed the 30-bit maximum */\n'
    '    if (id > SHAPER_HANDLE_ID_MAX)\n'
    '        return -ERANGE;\n'
    '\n'
    '    /* Construct handle from scope and id */\n'
    '    handle = SHAPER_MAKE_HANDLE(scope, id);'
)
assert old_block in code, "Bugs 2/3/4 target not found"
code = code.replace(old_block, new_block)

# ── Bug 6: Add duplicate leaf detection in shaper_group ──────────────
old_resolve = (
    '    /* Resolve leaf handles to node indices */\n'
    '    for (int i = 0; i < n_leaves; i++) {'
)
new_resolve = (
    '    /* Reject duplicate leaf handles */\n'
    '    for (int a = 0; a < n_leaves; a++) {\n'
    '        for (int b = a + 1; b < n_leaves; b++) {\n'
    '            if (leaf_handles[a] == leaf_handles[b])\n'
    '                return -EINVAL;\n'
    '        }\n'
    '    }\n'
    '\n'
    '    /* Resolve leaf handles to node indices */\n'
    '    for (int i = 0; i < n_leaves; i++) {'
)
assert old_resolve in code, "Bug 6 target not found"
code = code.replace(old_resolve, new_resolve)

# ── Bug 7: Remove erroneous single-child GROUP rejection in validate_tree
old_validate = (
    '        /* GROUP nodes must have multiple children */\n'
    '        if (SHAPER_HANDLE_SCOPE(ctx->nodes[i].handle) == SHAPER_SCOPE_GROUP &&\n'
    '            ctx->nodes[i].child_count < 2)\n'
    '            return -6;\n'
)
assert old_validate in code, "Bug 7 target not found"
code = code.replace(old_validate, '')

# ── Design: Implement shaper_rebalance ───────────────────────────────
# Replace the stub with a full post-order DFS proportional scaling algorithm.
old_rebalance = (
    'int shaper_rebalance(struct shaper_ctx *ctx, int subtree_root)\n'
    '{\n'
    '    (void)ctx;\n'
    '    (void)subtree_root;\n'
    '    /* TODO: implement per SPEC.md */\n'
    '    return 0;\n'
    '}'
)

new_rebalance = (
    '/* Recursive helper: post-order DFS rebalancing. */\n'
    'static int _rebalance_node(struct shaper_ctx *ctx, int idx)\n'
    '{\n'
    '    struct shaper_node *node = &ctx->nodes[idx];\n'
    '    int j;\n'
    '    uint64_t total, parent_rate, new_sum, remainder;\n'
    '\n'
    '    /* Recurse into child subtrees first (post-order) */\n'
    '    for (j = 0; j < node->child_count; j++) {\n'
    '        int ci = node->children[j];\n'
    '        if (ctx->nodes[ci].child_count > 0) {\n'
    '            int ret = _rebalance_node(ctx, ci);\n'
    '            if (ret < 0) return ret;\n'
    '        }\n'
    '    }\n'
    '\n'
    '    if (node->child_count == 0)\n'
    '        return 0;\n'
    '\n'
    '    /* Compute sum of children rates */\n'
    '    total = 0;\n'
    '    for (j = 0; j < node->child_count; j++)\n'
    '        total += ctx->nodes[node->children[j]].rate_bps;\n'
    '\n'
    '    /* No scaling needed if within limits or all zero */\n'
    '    if (total == 0 || total <= node->rate_bps)\n'
    '        return 0;\n'
    '\n'
    '    /* Proportional scaling: new_rate = floor(old * parent / total) */\n'
    '    parent_rate = node->rate_bps;\n'
    '    new_sum = 0;\n'
    '    for (j = 0; j < node->child_count; j++) {\n'
    '        int ci = node->children[j];\n'
    '        uint64_t old_rate = ctx->nodes[ci].rate_bps;\n'
    '        uint64_t new_rate = (uint64_t)(((__uint128_t)old_rate * parent_rate) / total);\n'
    '        ctx->nodes[ci].rate_bps = new_rate;\n'
    '        new_sum += new_rate;\n'
    '    }\n'
    '\n'
    '    /* Distribute remainder to first non-zero-rate children */\n'
    '    remainder = parent_rate - new_sum;\n'
    '    for (j = 0; j < node->child_count && remainder > 0; j++) {\n'
    '        int ci = node->children[j];\n'
    '        if (ctx->nodes[ci].rate_bps > 0) {\n'
    '            ctx->nodes[ci].rate_bps += 1;\n'
    '            remainder--;\n'
    '        }\n'
    '    }\n'
    '\n'
    '    return 0;\n'
    '}\n'
    '\n'
    'int shaper_rebalance(struct shaper_ctx *ctx, int subtree_root)\n'
    '{\n'
    '    if (subtree_root < 0 || subtree_root >= MAX_NODES)\n'
    '        return -EINVAL;\n'
    '    if (!ctx->nodes[subtree_root].used)\n'
    '        return -EINVAL;\n'
    '    return _rebalance_node(ctx, subtree_root);\n'
    '}'
)

assert old_rebalance in code, "Rebalance stub not found"
code = code.replace(old_rebalance, new_rebalance)

# ── Verify we actually changed something ─────────────────────────────
assert code != original, "No changes applied"

with open('/app/shaper.c', 'w') as f:
    f.write(code)

print("All 7 bugs fixed and shaper_rebalance implemented in /app/shaper.c")
