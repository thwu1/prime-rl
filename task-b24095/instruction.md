A simplified SQL logical query plan optimizer framework is set up at `/app/`. The framework represents query plans as trees of `PlanNode` objects with `Expr` expression trees (defined in `/app/plan_ir.py`). Seventeen unoptimized query plans are provided in `/app/plans/` as JSON files.

Implement the `optimize()` function in `/app/optimizer.py` so that it applies the following five optimization rules to each plan, in order, repeating the full sequence 3 times for fixpoint convergence:

1. **eliminate_filter**: Drop filters whose predicate is always true (e.g., `1 = 1`). Replace filters whose predicate is always false (e.g., `1 = 0`) with an `empty_relation` node preserving the output schema.

2. **propagate_empty_relation**: If a unary node (filter, project, sort, limit, subquery_alias) has an empty-relation child (not `produce_one_row`), replace the entire subtree with an empty relation. For joins: inner/cross join with any empty child → empty; left join with empty left → empty; right join with empty right → empty; full join → empty only if both sides are empty. For unions, remove empty branches; if all branches are empty, the union is empty.

3. **eliminate_cross_join**: When a `filter` node sits above a `cross` join and the filter's predicate contains an equijoin condition referencing both join sides, rewrite the cross join to an `inner` join with that condition, keeping any remaining filter predicates as a separate filter above. Handle nested cross joins (multi-way joins) by extracting all equijoin pairs and converting each qualifying cross join. Non-equality predicates that reference both sides should become `join_filter`.

4. **push_down_filter**: Push filter predicates through:
   - **projection**: push if all referenced columns pass through
   - **inner join**: split conjuncts; push predicates that reference only the left child below the join on the left, and similarly for right-only predicates on the right; predicates referencing both sides stay above
   - **left join**: push left-only predicates to the left child; predicates on the right (null-extended) side stay above the join since they may convert the join semantics
   - **aggregate**: push predicates that reference only group-by columns below the aggregate
   - **subquery_alias**: rewrite table references and push through
   - **sort**: push through freely

5. **push_down_limit**: Merge nested `limit` nodes using the formula: `new_skip = parent_skip + child_skip`, `new_fetch = min(parent_fetch, child_fetch - parent_skip)` (clamped to 0). Push limits into each branch of a `union` (each branch gets `limit 0, skip+fetch`).

After implementing, run `python3 /app/optimizer.py` to produce optimized plans in `/app/optimized/`.