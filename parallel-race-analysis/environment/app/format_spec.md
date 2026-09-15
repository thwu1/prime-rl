# Computation Graph Specification Format
#
# A .cg file defines a parallel computation graph using Habanero-style
# async/finish task-parallel constructs.
#
# ## Syntax
#
# ### Node Declaration
#   NODE <id> WEIGHT <w>
#     Declares a computation node with integer id and positive integer weight.
#
# ### Memory Access Declaration (must follow its NODE line)
#   ACCESS <node_id> READ <var>
#   ACCESS <node_id> WRITE <var>
#     Declares that node <node_id> reads or writes variable <var>.
#     A node may have multiple ACCESS lines.
#
# ### Edge Types
#   CONTINUE <src> -> <dst>
#     Sequential continuation edge: src completes before dst starts.
#     Models sequential control flow within a task.
#
#   SPAWN <src> -> <dst>
#     Async spawn edge: src spawns dst as a child async task.
#     src happens-before dst, but src's continuation may run in parallel with dst.
#
#   FUTURE_GET <src> -> <dst>
#     Future resolution edge: dst blocks until src completes.
#     Creates a happens-before from src to dst even across different async scopes.
#
# ### Finish Scope
#   FINISH_SCOPE <scope_id> PARENT <parent_scope_id|NONE>
#     Declares a finish scope. PARENT NONE means top-level.
#
#   FINISH_MEMBER <scope_id> <node_id>
#     Assigns node to a finish scope. A node belongs to exactly one finish scope.
#
#   FINISH_END <scope_id> <node_id>
#     The node that executes after ALL tasks in the finish scope complete.
#     All nodes in the scope happen-before this end node.
#     This creates join edges from every node in the scope to the end node.
#
# ## Happens-Before Rules
# 1. If CONTINUE a -> b, then a HB b.
# 2. If SPAWN a -> b, then a HB b.
# 3. If FUTURE_GET a -> b, then a HB b.
# 4. If node x is in FINISH_SCOPE s and node e is the FINISH_END of s,
#    then x HB e (unless x == e).
# 5. HB is transitively closed.
#
# ## May-Happen-in-Parallel
# Nodes u and v are MHP iff NOT (u HB v) AND NOT (v HB u) AND u != v.
#
# ## Data Race
# A data race exists between MHP nodes u and v if they both access the
# same variable and at least one access is a WRITE.
