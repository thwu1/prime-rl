#!/usr/bin/env python3
"""Apply the four fixes to the Volcano/Cascades optimizer.

Fix 1 — cost.py: CostModel.is_better comparison is inverted (> → <).
Fix 2 — rules.py / HashJoinBuilder: reorder children, fix memory cost.
Fix 3 — rules.py / JoinReorderBySize: sort by table_size not row_count.
Fix 4 — rules.py / FilterPushDown: implement transform method.
"""
import pathlib

COST_PY = pathlib.Path("/app/planner/cost.py")
RULES_PY = pathlib.Path("/app/planner/rules.py")

# ── Fix 1: CostModel.is_better ──────────────────────────────────────────────
src = COST_PY.read_text()
src = src.replace(
    "return self.total_cost(candidate) > self.total_cost(current_best)",
    "return self.total_cost(candidate) < self.total_cost(current_best)",
)
COST_PY.write_text(src)
print("[fix 1] cost.py — is_better comparison direction fixed")

# ── Fix 2: HashJoinBuilder.build — reorder + correct memory ─────────────────
src = RULES_PY.read_text()

# Replace the body of HashJoinBuilder.build
src = src.replace(
    "        # Use children in the order they arrive — no reordering.\n"
    "        left_child, right_child = children[0], children[1]",
    "        # Reorder so the smaller view is the build (hash-table) side.\n"
    "        if self._view_size(children[0]) <= self._view_size(children[1]):\n"
    "            build_child, probe_child = children[0], children[1]\n"
    "        else:\n"
    "            build_child, probe_child = children[1], children[0]",
)

# Fix the cost variable references
src = src.replace(
    "        est_loop = max(left_child.estimations().loop_iterations,\n"
    "                       right_child.estimations().loop_iterations)\n"
    "        est_row = left_child.estimations().row_size + right_child.estimations().row_size\n"
    "\n"
    "        # Self-cost of the hash join operation.\n"
    "        cpu_cost = left_child.estimations().loop_iterations\n"
    "        memory_cost = self._view_size(right_child)  # hash-table memory\n"
    "        time_cost = right_child.estimations().loop_iterations",
    "        est_loop = max(build_child.estimations().loop_iterations,\n"
    "                       probe_child.estimations().loop_iterations)\n"
    "        est_row = build_child.estimations().row_size + probe_child.estimations().row_size\n"
    "\n"
    "        # Self-cost of the hash join operation.\n"
    "        cpu_cost = build_child.estimations().loop_iterations\n"
    "        memory_cost = self._view_size(build_child)  # hash-table memory\n"
    "        time_cost = probe_child.estimations().loop_iterations",
)

src = src.replace(
    "        total_cpu = cpu_cost + left_child.cost().cpu + right_child.cost().cpu\n"
    "        total_mem = memory_cost + left_child.cost().memory + right_child.cost().memory\n"
    "        total_time = time_cost + left_child.cost().time + right_child.cost().time",
    "        total_cpu = cpu_cost + build_child.cost().cpu + probe_child.cost().cpu\n"
    "        total_mem = memory_cost + build_child.cost().memory + probe_child.cost().memory\n"
    "        total_time = time_cost + build_child.cost().time + probe_child.cost().time",
)

src = src.replace(
    '        return PhysicalPlan("HASH_JOIN", cost, est, set(), [left_child, right_child])',
    '        return PhysicalPlan("HASH_JOIN", cost, est, set(), [build_child, probe_child])',
)

print("[fix 2] rules.py — HashJoinBuilder: reorder children + correct memory cost")

# ── Fix 3: JoinReorderBySize — use estimated_table_size ──────────────────────
src = src.replace(
    "key=lambda s: ctx.stats_provider(s.table.name).estimated_row_count,",
    "key=lambda s: ctx.stats_provider(s.table.name).estimated_table_size,",
)
print("[fix 3] rules.py — JoinReorderBySize: sort by estimated_table_size")

# ── Fix 4: FilterPushDown.transform ──────────────────────────────────────────
src = src.replace(
    '        raise NotImplementedError("FilterPushDown.transform not yet implemented")',
    '        plan = expression.plan          # LPFilter\n'
    '        join = plan.child               # LPJoin\n'
    '        left_tables = join.left.collect_tables()\n'
    '        right_tables = join.right.collect_tables()\n'
    '\n'
    '        cond_tables = {c.field.table.name for c in plan.conditions}\n'
    '\n'
    '        if cond_tables <= left_tables:\n'
    '            new_plan = LPJoin(\n'
    '                LPFilter(plan.conditions, join.left),\n'
    '                join.right,\n'
    '                join.on,\n'
    '            )\n'
    '        elif cond_tables <= right_tables:\n'
    '            new_plan = LPJoin(\n'
    '                join.left,\n'
    '                LPFilter(plan.conditions, join.right),\n'
    '                join.on,\n'
    '            )\n'
    '        else:\n'
    '            # Cannot push — conditions span both sides.\n'
    '            return expression\n'
    '\n'
    '        return ctx.memo.get_or_create_expression(new_plan)',
)
print("[fix 4] rules.py — FilterPushDown.transform implemented")

RULES_PY.write_text(src)
print("All fixes applied.")
