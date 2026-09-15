#!/usr/bin/env python3
"""
Fix all bugs in /app/shaper.c, /app/test_shaper.c, and /app/Makefile.

Each fix is applied as a targeted string replacement, identified by
the unique surrounding code context.

"""

import sys

# ======================================================================
# Fix 0: Makefile — enable warnings and fix ASAN target
# ======================================================================

mf_path = "/app/Makefile"
with open(mf_path, "r") as f:
    mf = f.read()
mf_orig = mf

# Remove -w, add -Wall -Wextra, change -O2 to -O0
mf = mf.replace(
    "CFLAGS  = -w -std=c11 -g -O2",
    "CFLAGS  = -Wall -Wextra -std=c11 -g -O0",
    1,
)

# Fix sanitize target: -fsanitize=addresses -> -fsanitize=address
mf = mf.replace("-fsanitize=addresses", "-fsanitize=address")

assert mf != mf_orig, "Makefile: no changes applied"
with open(mf_path, "w") as f:
    f.write(mf)
print(f"Fixed Makefile")

# ======================================================================
# Fix shaper.c
# ======================================================================

sc_path = "/app/shaper.c"
with open(sc_path, "r") as f:
    src = f.read()
src_orig = src

# ------------------------------------------------------------------
# Bug 1-3: shaper_handle_validate — missing QUEUE/NETDEV/bit-width
# ------------------------------------------------------------------

old_validate = """\t/* NODE scope: any id (including UNSET for auto-assign) is valid,
\t * no additional constraints apply. */
\tif (h->scope == SHAPER_SCOPE_NODE)
\t\treturn 0;

\treturn 0;"""

new_validate = """\t/* NODE scope: any id (including UNSET for auto-assign) is valid. */
\tif (h->scope == SHAPER_SCOPE_NODE)
\t\treturn 0;

\t/* QUEUE scope requires a specific queue index */
\tif (h->scope == SHAPER_SCOPE_QUEUE && h->id == SHAPER_HANDLE_ID_UNSET)
\t\treturn -EINVAL;

\t/* NETDEV scope is a per-device singleton: id must be 0 */
\tif (h->scope == SHAPER_SCOPE_NETDEV && h->id != 0)
\t\treturn -EINVAL;

\t/* All non-UNSET ids must fit in SHAPER_HANDLE_ID_BITS bits */
\tif (h->id != SHAPER_HANDLE_ID_UNSET &&
\t    h->id >= (1u << SHAPER_HANDLE_ID_BITS))
\t\treturn -EINVAL;

\treturn 0;"""

assert old_validate in src, "Cannot locate handle_validate bug site"
src = src.replace(old_validate, new_validate, 1)

# ------------------------------------------------------------------
# Bug 4: shaper_node_is_active — inverted polarity
# ------------------------------------------------------------------

old_active = "\treturn !ctx->nodes[idx].active;"
new_active = "\treturn ctx->nodes[idx].active;"

assert old_active in src, "Cannot locate is_active bug site"
src = src.replace(old_active, new_active, 1)

# ------------------------------------------------------------------
# Bug 5: shaper_group_set_leaves — missing duplicate leaf detection
# ------------------------------------------------------------------

old_group = """\t\tif (!ctx->nodes[leaves[i]].active)
\t\t\treturn -ENOENT;
\t}"""

new_group = """\t\tif (!ctx->nodes[leaves[i]].active)
\t\t\treturn -ENOENT;

\t\t/* Reject duplicate leaf indices */
\t\tfor (int j = 0; j < i; j++) {
\t\t\tif (leaves[j] == leaves[i])
\t\t\t\treturn -EINVAL;
\t\t}
\t}"""

assert old_group in src, "Cannot locate group_set_leaves bug site"
src = src.replace(old_group, new_group, 1)

# ------------------------------------------------------------------
# Bug 6: shaper_batch_commit — wrong operation ordering
# ------------------------------------------------------------------

old_commit = """\t/* Phase 1: deletions */
\tfor (i = 0; i < n_ops; i++) {
\t\tif (ops[i].type != SHAPER_OP_DELETE)
\t\t\tcontinue;
\t\tret = shaper_node_delete(ctx, ops[i].node_idx);
\t\tif (ret)
\t\t\treturn ret;
\t}

\t/* Phase 2: additions */
\tfor (i = 0; i < n_ops; i++) {
\t\tif (ops[i].type != SHAPER_OP_ADD)
\t\t\tcontinue;
\t\tret = shaper_node_add(ctx, ops[i].node_idx, &ops[i].handle,
\t\t\t\t      ops[i].rate, ops[i].priority,
\t\t\t\t      ops[i].parent_idx);
\t\tif (ret)
\t\t\treturn ret;
\t}

\t/* Phase 3: in-place updates */
\tfor (i = 0; i < n_ops; i++) {
\t\tif (ops[i].type != SHAPER_OP_UPDATE)
\t\t\tcontinue;
\t\tif (ops[i].node_idx < 0 || ops[i].node_idx >= SHAPER_MAX_NODES)
\t\t\treturn -EINVAL;
\t\tif (!ctx->nodes[ops[i].node_idx].active)
\t\t\treturn -ENOENT;
\t\tctx->nodes[ops[i].node_idx].rate_bytes_per_sec = ops[i].rate;
\t\tctx->nodes[ops[i].node_idx].priority = ops[i].priority;
\t}

\treturn 0;"""

new_commit = """\t/* Phase 1: additions */
\tfor (i = 0; i < n_ops; i++) {
\t\tif (ops[i].type != SHAPER_OP_ADD)
\t\t\tcontinue;
\t\tret = shaper_node_add(ctx, ops[i].node_idx, &ops[i].handle,
\t\t\t\t      ops[i].rate, ops[i].priority,
\t\t\t\t      ops[i].parent_idx);
\t\tif (ret)
\t\t\treturn ret;
\t}

\t/* Phase 2: in-place updates */
\tfor (i = 0; i < n_ops; i++) {
\t\tif (ops[i].type != SHAPER_OP_UPDATE)
\t\t\tcontinue;
\t\tif (ops[i].node_idx < 0 || ops[i].node_idx >= SHAPER_MAX_NODES)
\t\t\treturn -EINVAL;
\t\tif (!ctx->nodes[ops[i].node_idx].active)
\t\t\treturn -ENOENT;
\t\tctx->nodes[ops[i].node_idx].rate_bytes_per_sec = ops[i].rate;
\t\tctx->nodes[ops[i].node_idx].priority = ops[i].priority;
\t}

\t/* Phase 3: deletions */
\tfor (i = 0; i < n_ops; i++) {
\t\tif (ops[i].type != SHAPER_OP_DELETE)
\t\t\tcontinue;
\t\tret = shaper_node_delete(ctx, ops[i].node_idx);
\t\tif (ret)
\t\t\treturn ret;
\t}

\treturn 0;"""

assert old_commit in src, "Cannot locate batch_commit bug site"
src = src.replace(old_commit, new_commit, 1)

# ------------------------------------------------------------------
# Bug 7: shaper_replace_child — missing backlog subtraction/reset
# ------------------------------------------------------------------

old_replace = """\t\t\t/* Adjust packet counter for old child's drained traffic */
\t\t\tparent->qlen -= ctx->nodes[old_idx].qlen;
\t\t\tctx->nodes[old_idx].qlen = 0;
\t\t\tctx->nodes[old_idx].parent_idx = -1;

\t\t\treturn 0;"""

new_replace = """\t\t\t/* Drain old child's counters from parent and reset */
\t\t\tparent->qlen -= ctx->nodes[old_idx].qlen;
\t\t\tparent->backlog_bytes -= ctx->nodes[old_idx].backlog_bytes;
\t\t\tctx->nodes[old_idx].qlen = 0;
\t\t\tctx->nodes[old_idx].backlog_bytes = 0;
\t\t\tctx->nodes[old_idx].parent_idx = -1;

\t\t\treturn 0;"""

assert old_replace in src, "Cannot locate replace_child bug site"
src = src.replace(old_replace, new_replace, 1)

# ------------------------------------------------------------------
# Bug 8: shaper_get_subtree_stats — use-after-free
# ------------------------------------------------------------------

old_subtree = """\tfree(visited);

\t/* Post-traversal sanity: verify the root was actually reached. */
\tif (!visited[root_idx])
\t\treturn -ENOENT;

\treturn 0;"""

new_subtree = """\tint root_visited = visited[root_idx];
\tfree(visited);

\t/* Post-traversal sanity: verify the root was actually reached. */
\tif (!root_visited)
\t\treturn -ENOENT;

\treturn 0;"""

assert old_subtree in src, "Cannot locate subtree_stats bug site"
src = src.replace(old_subtree, new_subtree, 1)

# ------------------------------------------------------------------
# Write patched shaper.c
# ------------------------------------------------------------------

assert src != src_orig, "shaper.c: no changes were applied"
with open(sc_path, "w") as f:
    f.write(src)
print(f"Applied 8 fixes to shaper.c")

# ======================================================================
# Fix test_shaper.c — wrong expectations + add new test
# ======================================================================

tc_path = "/app/test_shaper.c"
with open(tc_path, "r") as f:
    tc = f.read()
tc_orig = tc

# ------------------------------------------------------------------
# Fix wrong backlog expectations in replace_child_reset test
# ------------------------------------------------------------------

tc = tc.replace(
    '\tASSERT_EQ(p_backlog, 2500,\n'
    '\t\t  "Parent backlog must retain committed reservation");',
    '\tASSERT_EQ(p_backlog, 0,\n'
    '\t\t  "Parent backlog must be 0 after child replacement");',
    1,
)

tc = tc.replace(
    '\tASSERT_EQ(o_backlog, 2500,\n'
    '\t\t  "Old child backlog must retain for audit trail");',
    '\tASSERT_EQ(o_backlog, 0,\n'
    '\t\t  "Old child backlog must be reset after replacement");',
    1,
)

# ------------------------------------------------------------------
# Add new test: batch_add_update_same
# ------------------------------------------------------------------

new_test_func = """
/* ================================================================== */
/*  Batch add + update same node test                                  */
/* ================================================================== */

/*
 * A batch containing ADD and UPDATE for the same node index must apply
 * both: the node is created by ADD and then modified by UPDATE.
 */
static int test_batch_add_update_same(void)
{
\tstruct shaper_ctx ctx;
\tstruct shaper_handle h_root = { .scope = SHAPER_SCOPE_NETDEV, .id = 0 };
\tstruct shaper_handle h_new  = { .scope = SHAPER_SCOPE_NODE,   .id = 5 };

\tshaper_ctx_init(&ctx);
\tshaper_node_add(&ctx, 0, &h_root, 1000000, 0, -1);

\tstruct shaper_op ops[2] = {
\t\t{
\t\t\t.type       = SHAPER_OP_ADD,
\t\t\t.node_idx   = 5,
\t\t\t.handle     = h_new,
\t\t\t.rate       = 500000,
\t\t\t.priority   = 1,
\t\t\t.parent_idx = 0,
\t\t},
\t\t{
\t\t\t.type       = SHAPER_OP_UPDATE,
\t\t\t.node_idx   = 5,
\t\t\t.rate       = 750000,
\t\t\t.priority   = 2,
\t\t},
\t};

\tint ret = shaper_batch_commit(&ctx, ops, 2);
\tASSERT_EQ(ret, 0, "Batch add+update on same node must succeed");

\tASSERT_TRUE(ctx.nodes[5].active,
\t\t    "Added node must be active after batch");
\tASSERT_EQ(ctx.nodes[5].rate_bytes_per_sec, 750000,
\t\t  "Rate must reflect the update value");
\tASSERT_EQ(ctx.nodes[5].priority, 2,
\t\t  "Priority must reflect the update value");

\tshaper_ctx_cleanup(&ctx);
\tTEST_PASS();
}
"""

# Insert new test function before the test dispatcher section
tc = tc.replace(
    "/* ================================================================== */\n"
    "/*  Main — test dispatcher",
    new_test_func +
    "/* ================================================================== */\n"
    "/*  Main — test dispatcher",
    1,
)

# Add new entry to test_table
tc = tc.replace(
    '\t{ "subtree_stats_basic",      test_subtree_stats_basic      },\n};',
    '\t{ "subtree_stats_basic",      test_subtree_stats_basic      },\n'
    '\t{ "batch_add_update_same",    test_batch_add_update_same    },\n};',
    1,
)

assert tc != tc_orig, "test_shaper.c: no changes were applied"
with open(tc_path, "w") as f:
    f.write(tc)
print(f"Fixed test expectations and added new test in test_shaper.c")
