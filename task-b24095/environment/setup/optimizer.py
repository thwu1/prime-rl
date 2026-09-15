"""
Query Plan Optimizer - Stub Implementation

Implement the optimize() function to apply the following optimization rules
in the specified order to a logical query plan:

1. eliminate_filter: Remove always-true filters; replace always-false filters with EmptyRelation
2. propagate_empty_relation: Collapse nodes whose children produce no rows
3. eliminate_cross_join: Convert cross joins with equijoin predicates in a parent filter to inner joins
4. push_down_filter: Push filter predicates through projections, joins, and aggregates
5. push_down_limit: Merge nested limits; push limits into union branches

Each rule should be applied bottom-up in a single pass, then the sequence repeats
for a fixed number of iterations (3 passes) to reach a fixpoint.

The plan IR is defined in /app/plan_ir.py. Plans are loaded from /app/plans/*.json.
Optimized plans should be written to /app/optimized/<same_filename>.json.

"""

import os
import sys
sys.path.insert(0, "/app")

from plan_ir import PlanNode, Expr, load_plan, save_plan


def optimize(plan: PlanNode) -> PlanNode:
    """
    Apply all optimization rules to the given plan.
    Return the optimized plan.
    """
    # TODO: Implement the optimizer
    # You must implement these rules:
    #
    # 1. eliminate_filter(plan) - Remove tautological filters
    # 2. propagate_empty_relation(plan) - Collapse plans with empty inputs
    # 3. eliminate_cross_join(plan) - Convert cross joins to inner joins
    # 4. push_down_filter(plan) - Push filters closer to data sources
    # 5. push_down_limit(plan) - Push limits closer to data sources
    #
    # Apply all rules in order, repeat 3 times for fixpoint convergence.
    raise NotImplementedError("Optimizer not yet implemented")


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
