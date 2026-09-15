A Volcano/Cascades cost-based query optimizer is implemented in `/app/planner/`. The optimizer parses simplified SQL, builds a logical plan, explores equivalent plans via transformation rules (projection push-down, join reorder, filter push-down), and selects the cheapest physical plan using a multi-dimensional cost model.

The optimizer has **three bugs** and **one missing feature** that cause it to produce incorrect or grossly suboptimal query execution plans:

1. The cost model's plan-comparison logic in `/app/planner/cost.py` does not correctly identify cheaper plans.
2. The hash-join physical plan builder in `/app/planner/rules.py` computes memory cost incorrectly — it does not account for which child should be the hash-table build side.
3. The join-reorder transformation rule in `/app/planner/rules.py` sorts tables by the wrong size metric, producing suboptimal join ordering when tables have very different row sizes.
4. The `FilterPushDown.transform` method in `/app/planner/rules.py` is unimplemented and must be completed so that filter predicates referencing only one side of a join are pushed below the join.

Fix all four issues so that the optimizer's test suite passes.