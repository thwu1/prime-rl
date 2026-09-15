"""
Solution: Full optimizer implementation.

"""

import os
import sys
import json
import copy

sys.path.insert(0, "/app")
from plan_ir import PlanNode, Expr, load_plan, save_plan, split_conjunction, conjunction


# =============================================================================
# Rule 1: Eliminate Filter
# =============================================================================
def eliminate_filter(plan: PlanNode) -> PlanNode:
    """Remove always-true filters; replace always-false with empty relation."""
    # First recurse into children
    plan.children = [eliminate_filter(c) for c in plan.children]

    if plan.kind != "filter":
        return plan

    pred = plan.predicate
    if pred is None:
        # No predicate, just return child
        return plan.children[0] if plan.children else plan

    if pred.is_always_true():
        # Drop the filter, return child
        return plan.children[0] if plan.children else plan

    if pred.is_always_false():
        # Replace with empty relation, preserving schema
        child = plan.children[0] if plan.children else None
        schema = []
        if child:
            for t, c in child.output_columns():
                schema.append(c)
        return PlanNode(kind="empty_relation", produce_one_row=False, empty_schema=schema)

    return plan


# =============================================================================
# Rule 2: Propagate Empty Relation
# =============================================================================
def propagate_empty_relation(plan: PlanNode) -> PlanNode:
    """Collapse nodes whose children produce empty relations."""
    # Recurse first (bottom-up)
    plan.children = [propagate_empty_relation(c) for c in plan.children]

    if plan.kind == "empty_relation":
        return plan

    # Unary operators: if child is empty, collapse
    if plan.kind in ("filter", "project", "sort", "subquery_alias", "limit"):
        if plan.children and plan.children[0].is_empty_relation():
            schema = []
            for t, c in plan.output_columns():
                schema.append(c)
            return PlanNode(kind="empty_relation", produce_one_row=False, empty_schema=schema)
        return plan

    if plan.kind == "join":
        if len(plan.children) < 2:
            return plan

        left_empty = plan.children[0].is_empty_relation()
        right_empty = plan.children[1].is_empty_relation()
        jt = plan.join_type or "inner"

        schema = []
        for t, c in plan.output_columns():
            schema.append(c)

        if jt in ("inner", "cross"):
            # Either side empty -> empty
            if left_empty or right_empty:
                return PlanNode(kind="empty_relation", produce_one_row=False, empty_schema=schema)

        elif jt == "left":
            # Left empty -> empty (no left rows to drive)
            if left_empty:
                return PlanNode(kind="empty_relation", produce_one_row=False, empty_schema=schema)
            # Right empty -> still produces left rows with NULLs, keep as-is

        elif jt == "right":
            # Right empty -> empty (no right rows to drive)
            if right_empty:
                return PlanNode(kind="empty_relation", produce_one_row=False, empty_schema=schema)
            # Left empty -> still produces right rows with NULLs, keep as-is

        elif jt == "full":
            # Only both empty -> empty
            if left_empty and right_empty:
                return PlanNode(kind="empty_relation", produce_one_row=False, empty_schema=schema)

        elif jt in ("left_semi", "left_anti"):
            if left_empty:
                return PlanNode(kind="empty_relation", produce_one_row=False, empty_schema=schema)
            if jt == "left_semi" and right_empty:
                return PlanNode(kind="empty_relation", produce_one_row=False, empty_schema=schema)

        elif jt in ("right_semi", "right_anti"):
            if right_empty:
                return PlanNode(kind="empty_relation", produce_one_row=False, empty_schema=schema)
            if jt == "right_semi" and left_empty:
                return PlanNode(kind="empty_relation", produce_one_row=False, empty_schema=schema)

        return plan

    if plan.kind == "union":
        # Remove empty branches
        non_empty = [c for c in plan.children if not c.is_empty_relation()]
        if not non_empty:
            schema = []
            for t, c in plan.output_columns():
                schema.append(c)
            return PlanNode(kind="empty_relation", produce_one_row=False, empty_schema=schema)
        if len(non_empty) == 1:
            return non_empty[0]
        plan.children = non_empty
        return plan

    return plan


# =============================================================================
# Rule 3: Eliminate Cross Join
# =============================================================================
def _collect_cross_join_inputs(node: PlanNode) -> list:
    """Flatten nested cross joins into a list of their leaf inputs."""
    if node.kind == "join" and (node.join_type == "cross" or node.join_type is None):
        inputs = []
        for c in node.children:
            inputs.extend(_collect_cross_join_inputs(c))
        return inputs
    return [node]


def _get_node_tables(node: PlanNode) -> set:
    """Get all table names reachable from this node, including alias names."""
    tables = node.child_tables()
    # Also include subquery alias names
    if node.kind == "subquery_alias" and node.alias_name:
        tables.add(node.alias_name)
    for c in node.children:
        tables |= _get_alias_names(c)
    return tables


def _get_alias_names(node: PlanNode) -> set:
    """Recursively collect subquery alias names."""
    names = set()
    if node.kind == "subquery_alias" and node.alias_name:
        names.add(node.alias_name)
    for c in node.children:
        names |= _get_alias_names(c)
    return names


def eliminate_cross_join(plan: PlanNode) -> PlanNode:
    """Convert cross joins with equijoin predicates to inner joins."""
    # Recurse first
    plan.children = [eliminate_cross_join(c) for c in plan.children]

    if plan.kind != "filter":
        return plan

    if not plan.children:
        return plan

    child = plan.children[0]

    # Check if child is a cross join (or nested cross joins)
    if child.kind != "join" or child.join_type != "cross":
        return plan

    # Collect all inputs from nested cross joins
    inputs = _collect_cross_join_inputs(child)
    if len(inputs) < 2:
        return plan

    # Split filter predicates
    predicates = split_conjunction(plan.predicate)

    # Classify predicates
    equijoin_preds = []  # (pred, left_tables, right_tables)
    residual_preds = []
    other_join_preds = []  # non-equality predicates referencing both sides

    for pred in predicates:
        tables = pred.tables_referenced()
        if pred.kind == "binary" and pred.op == "=":
            left_tables = pred.left.tables_referenced() if pred.left else set()
            right_tables = pred.right.tables_referenced() if pred.right else set()
            if left_tables and right_tables and not left_tables.intersection(right_tables):
                equijoin_preds.append(pred)
                continue
        if len(tables) > 1:
            # References multiple tables
            other_join_preds.append(pred)
        else:
            residual_preds.append(pred)

    if not equijoin_preds and not other_join_preds:
        return plan

    # Build the join tree from inputs using equijoin predicates
    # Start with the first input, then join subsequent inputs
    result = inputs[0]
    remaining_inputs = list(inputs[1:])
    used_equijoin = set()

    for inp in remaining_inputs:
        inp_tables = _get_node_tables(inp)
        result_tables = _get_node_tables(result)

        # Find equijoin predicates that connect result_tables with inp_tables
        join_conds = []
        join_filters = []

        for i, eq in enumerate(equijoin_preds):
            if i in used_equijoin:
                continue
            left_t = eq.left.tables_referenced() if eq.left else set()
            right_t = eq.right.tables_referenced() if eq.right else set()

            if (left_t.issubset(result_tables) and right_t.issubset(inp_tables)) or \
               (right_t.issubset(result_tables) and left_t.issubset(inp_tables)):
                join_conds.append(eq)
                used_equijoin.add(i)

        # Check for non-equality predicates that should become join_filter
        used_other = []
        for i, pred in enumerate(other_join_preds):
            pred_tables = pred.tables_referenced()
            if pred_tables.issubset(result_tables | inp_tables) and \
               not pred_tables.issubset(result_tables) and \
               not pred_tables.issubset(inp_tables):
                join_filters.append(pred)
                used_other.append(i)

        for i in sorted(used_other, reverse=True):
            other_join_preds.pop(i)

        if join_conds:
            cond = conjunction(join_conds)
            jf = conjunction(join_filters) if join_filters else None
            result = PlanNode(
                kind="join",
                join_type="inner",
                join_condition=cond,
                join_filter=jf,
                children=[result, inp]
            )
        else:
            # No equijoin found for this input; keep as cross join
            jf = conjunction(join_filters) if join_filters else None
            result = PlanNode(
                kind="join",
                join_type="cross" if not jf else "inner",
                join_condition=None if not jf else None,
                join_filter=jf,
                children=[result, inp]
            )

    # Add remaining unused equijoin preds and other_join_preds to residual
    for i, eq in enumerate(equijoin_preds):
        if i not in used_equijoin:
            residual_preds.append(eq)
    residual_preds.extend(other_join_preds)

    if residual_preds:
        result = PlanNode(
            kind="filter",
            predicate=conjunction(residual_preds),
            children=[result]
        )

    return result


# =============================================================================
# Rule 4: Push Down Filter
# =============================================================================
def push_down_filter(plan: PlanNode) -> PlanNode:
    """Push filter predicates closer to data sources."""
    # Recurse first
    plan.children = [push_down_filter(c) for c in plan.children]

    if plan.kind != "filter" or not plan.children:
        return plan

    pred = plan.predicate
    if pred is None:
        return plan.children[0]

    child = plan.children[0]

    # Push through subquery alias
    if child.kind == "subquery_alias":
        alias = child.alias_name
        inner = child.children[0] if child.children else None
        if inner:
            # Rewrite table references from alias to inner tables
            new_pred = _rewrite_alias_refs(pred, alias, inner)
            new_filter = PlanNode(kind="filter", predicate=new_pred, children=[inner])
            # Recurse to push further
            new_filter = push_down_filter(new_filter)
            child.children = [new_filter]
            return child
        return plan

    # Push through projection
    if child.kind == "project":
        # Check if filter references only columns that pass through the projection
        child_inner = child.children[0] if child.children else None
        if child_inner:
            # Check if all columns in the predicate are available below the projection
            cols = pred.columns_referenced()
            proj_passes = set()
            for p in (child.projections or []):
                if p.kind == "column":
                    proj_passes.add((p.table, p.column))
                elif p.kind == "wildcard":
                    if child_inner:
                        proj_passes.update(child_inner.output_columns())
                elif p.kind == "alias":
                    proj_passes.add((None, p.alias))

            # If all referenced columns are in the projection pass-through, push down
            can_push = True
            for col_ref in cols:
                if col_ref not in proj_passes:
                    # Try without table qualifier
                    found = False
                    for pt, pc in proj_passes:
                        if pc == col_ref[1]:
                            found = True
                            break
                    if not found:
                        can_push = False
                        break

            if can_push:
                new_filter = PlanNode(kind="filter", predicate=pred, children=[child_inner])
                new_filter = push_down_filter(new_filter)
                child.children = [new_filter]
                return child

        return plan

    # Push through sort
    if child.kind == "sort":
        child_inner = child.children[0] if child.children else None
        if child_inner:
            new_filter = PlanNode(kind="filter", predicate=pred, children=[child_inner])
            new_filter = push_down_filter(new_filter)
            child.children = [new_filter]
            return child
        return plan

    # Push through inner join
    if child.kind == "join" and child.join_type == "inner":
        return _push_filter_through_inner_join(pred, child)

    # Push through left join
    if child.kind == "join" and child.join_type == "left":
        return _push_filter_through_left_join(pred, child)

    # Push through aggregate
    if child.kind == "aggregate":
        return _push_filter_through_aggregate(pred, child)

    return plan


def _rewrite_alias_refs(expr: Expr, alias: str, inner: PlanNode) -> Expr:
    """Rewrite expression that references alias.column to use inner's table names."""
    if expr.kind == "column" and expr.table == alias:
        # Find the matching column in the inner node
        inner_cols = inner.output_columns()
        for t, c in inner_cols:
            if c == expr.column:
                return Expr(kind="column", table=t, column=c)
        # If not found, just strip the alias
        return Expr(kind="column", table=None, column=expr.column)

    new_expr = expr.deep_copy()
    if new_expr.left:
        new_expr.left = _rewrite_alias_refs(new_expr.left, alias, inner)
    if new_expr.right:
        new_expr.right = _rewrite_alias_refs(new_expr.right, alias, inner)
    if new_expr.operand:
        new_expr.operand = _rewrite_alias_refs(new_expr.operand, alias, inner)
    if new_expr.expr:
        new_expr.expr = _rewrite_alias_refs(new_expr.expr, alias, inner)
    if new_expr.sort_expr:
        new_expr.sort_expr = _rewrite_alias_refs(new_expr.sort_expr, alias, inner)
    if new_expr.args:
        new_expr.args = [_rewrite_alias_refs(a, alias, inner) if isinstance(a, Expr) else a for a in new_expr.args]
    if new_expr.scalar_args:
        new_expr.scalar_args = [_rewrite_alias_refs(a, alias, inner) if isinstance(a, Expr) else a for a in new_expr.scalar_args]
    return new_expr


def _push_filter_through_inner_join(pred: Expr, join: PlanNode) -> PlanNode:
    """Push filter conjuncts through inner join to appropriate sides."""
    conjuncts = split_conjunction(pred)

    left_tables = _get_node_tables(join.children[0]) if join.children else set()
    right_tables = _get_node_tables(join.children[1]) if len(join.children) > 1 else set()

    # Also consider alias names
    if join.children and join.children[0].kind == "subquery_alias":
        left_tables.add(join.children[0].alias_name)
    if len(join.children) > 1 and join.children[1].kind == "subquery_alias":
        right_tables.add(join.children[1].alias_name)

    left_preds = []
    right_preds = []
    remaining = []

    for c in conjuncts:
        tables = c.tables_referenced()
        if tables and tables.issubset(left_tables):
            left_preds.append(c)
        elif tables and tables.issubset(right_tables):
            right_preds.append(c)
        else:
            remaining.append(c)

    # Push left predicates
    if left_preds and join.children:
        left_filter = PlanNode(kind="filter", predicate=conjunction(left_preds), children=[join.children[0]])
        left_filter = push_down_filter(left_filter)
        join.children[0] = left_filter

    # Push right predicates
    if right_preds and len(join.children) > 1:
        right_filter = PlanNode(kind="filter", predicate=conjunction(right_preds), children=[join.children[1]])
        right_filter = push_down_filter(right_filter)
        join.children[1] = right_filter

    if remaining:
        return PlanNode(kind="filter", predicate=conjunction(remaining), children=[join])
    return join


def _push_filter_through_left_join(pred: Expr, join: PlanNode) -> PlanNode:
    """Push filter conjuncts through left join - only left-only preds can push to left child."""
    conjuncts = split_conjunction(pred)

    left_tables = _get_node_tables(join.children[0]) if join.children else set()
    right_tables = _get_node_tables(join.children[1]) if len(join.children) > 1 else set()

    if join.children and join.children[0].kind == "subquery_alias":
        left_tables.add(join.children[0].alias_name)
    if len(join.children) > 1 and join.children[1].kind == "subquery_alias":
        right_tables.add(join.children[1].alias_name)

    left_preds = []
    remaining = []

    for c in conjuncts:
        tables = c.tables_referenced()
        if tables and tables.issubset(left_tables):
            left_preds.append(c)
        else:
            # For left join: right-side and cross-side predicates stay above
            remaining.append(c)

    if left_preds and join.children:
        left_filter = PlanNode(kind="filter", predicate=conjunction(left_preds), children=[join.children[0]])
        left_filter = push_down_filter(left_filter)
        join.children[0] = left_filter

    if remaining:
        return PlanNode(kind="filter", predicate=conjunction(remaining), children=[join])
    return join


def _push_filter_through_aggregate(pred: Expr, agg: PlanNode) -> PlanNode:
    """Push filter predicates that reference only group-by columns below the aggregate."""
    conjuncts = split_conjunction(pred)

    # Get group-by column names
    group_cols = set()
    for g in (agg.group_by or []):
        if g.kind == "column":
            group_cols.add((g.table, g.column))
            group_cols.add((None, g.column))  # also match unqualified

    pushable = []
    remaining = []

    for c in conjuncts:
        cols = c.columns_referenced()
        # Check if all referenced columns are group-by columns
        can_push = True
        for col_ref in cols:
            if col_ref not in group_cols:
                # Try matching just column name
                found = False
                for gt, gc in group_cols:
                    if gc == col_ref[1]:
                        found = True
                        break
                if not found:
                    can_push = False
                    break
        if can_push:
            # Rewrite column references to use the table from group_by
            rewritten = _rewrite_to_group_by_tables(c, agg.group_by)
            pushable.append(rewritten)
        else:
            remaining.append(c)

    if pushable and agg.children:
        inner_filter = PlanNode(kind="filter", predicate=conjunction(pushable), children=[agg.children[0]])
        inner_filter = push_down_filter(inner_filter)
        agg.children[0] = inner_filter

    if remaining:
        return PlanNode(kind="filter", predicate=conjunction(remaining), children=[agg])
    return agg


def _rewrite_to_group_by_tables(expr: Expr, group_by: list) -> Expr:
    """Rewrite expression columns to match group-by table references."""
    if expr.kind == "column":
        for g in (group_by or []):
            if g.kind == "column" and g.column == expr.column:
                return Expr(kind="column", table=g.table, column=g.column)
        return expr

    new_expr = expr.deep_copy()
    if new_expr.left:
        new_expr.left = _rewrite_to_group_by_tables(new_expr.left, group_by)
    if new_expr.right:
        new_expr.right = _rewrite_to_group_by_tables(new_expr.right, group_by)
    if new_expr.operand:
        new_expr.operand = _rewrite_to_group_by_tables(new_expr.operand, group_by)
    return new_expr


# =============================================================================
# Rule 5: Push Down Limit
# =============================================================================
def push_down_limit(plan: PlanNode) -> PlanNode:
    """Merge nested limits; push limits into union branches."""
    # Recurse first
    plan.children = [push_down_limit(c) for c in plan.children]

    if plan.kind != "limit":
        return plan

    if not plan.children:
        return plan

    child = plan.children[0]

    # Merge nested limits
    if child.kind == "limit":
        parent_skip = plan.skip or 0
        parent_fetch = plan.fetch
        child_skip = child.skip or 0
        child_fetch = child.fetch

        new_skip = parent_skip + child_skip

        if parent_fetch is not None and child_fetch is not None:
            new_fetch = min(parent_fetch, max(0, child_fetch - parent_skip))
        elif parent_fetch is not None:
            new_fetch = parent_fetch
        elif child_fetch is not None:
            new_fetch = max(0, child_fetch - parent_skip)
        else:
            new_fetch = None

        merged = PlanNode(
            kind="limit",
            skip=new_skip,
            fetch=new_fetch,
            children=child.children
        )
        # Recurse again in case of triple nesting
        return push_down_limit(merged)

    # Push limit into union branches
    if child.kind == "union" or (child.kind == "subquery_alias" and child.children and child.children[0].kind == "union"):
        target = child
        if child.kind == "subquery_alias":
            target = child.children[0]

        skip = plan.skip or 0
        fetch = plan.fetch
        if fetch is not None:
            branch_limit = skip + fetch
            new_branches = []
            for branch in target.children:
                limited = PlanNode(kind="limit", skip=0, fetch=branch_limit, children=[branch])
                new_branches.append(limited)
            target.children = new_branches

    return plan


# =============================================================================
# Main optimize function
# =============================================================================
def optimize(plan: PlanNode) -> PlanNode:
    """Apply all optimization rules in order, 3 passes for fixpoint."""
    for _ in range(3):
        plan = eliminate_filter(plan)
        plan = propagate_empty_relation(plan)
        plan = eliminate_cross_join(plan)
        plan = push_down_filter(plan)
        plan = push_down_limit(plan)
    return plan


def main():
    plans_dir = "/app/plans"
    output_dir = "/app/optimized"
    os.makedirs(output_dir, exist_ok=True)

    plan_files = sorted(f for f in os.listdir(plans_dir) if f.endswith(".json"))
    for pf in plan_files:
        plan = load_plan(os.path.join(plans_dir, pf))
        optimized = optimize(plan)
        save_plan(optimized, os.path.join(output_dir, pf))
        print(f"Optimized: {pf}")

    print(f"\nDone. {len(plan_files)} plans optimized.")


if __name__ == "__main__":
    main()
