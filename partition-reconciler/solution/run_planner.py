#!/usr/bin/env python3
"""Cost-aware reconciliation planner.


Reads the corrected pipeline state and cost configuration, identifies stale
partitions, and produces an optimal re-materialization plan that respects
budget constraints and cascade dependencies.
"""

import json
import sys
import yaml

sys.path.insert(0, "/app")

from config_loader import load_pipeline
from db_store import SqliteMaterializationStore
from reconciler import Reconciler


def main():
    # Load cost configuration
    with open("/app/costs.yaml") as f:
        cost_config = yaml.safe_load(f)
    costs = cost_config["costs"]
    budget = float(cost_config["budget"])

    # Load pipeline graph and materialization state
    graph = load_pipeline("/app/pipeline.yaml")
    store = SqliteMaterializationStore("/app/warehouse.db")

    # Run reconciliation to identify stale partitions
    result = Reconciler(graph, store).reconcile()
    store.close()

    # Collect all stale partitions in topological order
    topo_order = graph.topo_sort()
    stale_partitions = []
    for asset_key in topo_order:
        for pk in sorted(result.get_stale(asset_key)):
            stale_partitions.append({
                "asset": asset_key,
                "partition": pk,
                "cost": float(costs.get(asset_key, 0)),
            })

    total_cost = sum(s["cost"] for s in stale_partitions)
    budget_exceeded = total_cost > budget

    # Cascade-aware greedy selection within budget.
    # Process stale partitions in topological order. A downstream partition
    # is only selectable if all its stale upstream dependencies are already
    # in the selected set (refreshing a downstream whose upstream is still
    # stale is wasteful).
    selected = []
    selected_set = set()  # (asset, partition) tuples
    remaining_budget = budget

    for sp in stale_partitions:
        asset_key = sp["asset"]
        partition_key = sp["partition"]
        node = graph.nodes[asset_key]

        # Check cascade constraint: every stale upstream partition that
        # maps to this partition must already be selected
        cascade_ok = True
        for upstream_key, mapping in node.deps.items():
            upstream_pks = mapping.get_upstream_keys(partition_key)
            for upstream_pk in upstream_pks:
                if upstream_pk in result.get_stale(upstream_key):
                    if (upstream_key, upstream_pk) not in selected_set:
                        cascade_ok = False
                        break
            if not cascade_ok:
                break

        # Select if cascade constraint is satisfied and fits in budget
        if cascade_ok and sp["cost"] <= remaining_budget:
            selected.append({
                "asset": asset_key,
                "partition": partition_key,
                "cost": sp["cost"],
            })
            selected_set.add((asset_key, partition_key))
            remaining_budget -= sp["cost"]

    plan = {
        "stale_partitions": [
            {"asset": s["asset"], "partition": s["partition"]}
            for s in stale_partitions
        ],
        "total_cost": total_cost,
        "budget": budget,
        "budget_exceeded": budget_exceeded,
        "selected": selected,
        "total_selected_cost": sum(s["cost"] for s in selected),
    }

    with open("/app/recon_plan.json", "w") as f:
        json.dump(plan, f, indent=2)

    print(f"Plan: {len(selected)}/{len(stale_partitions)} partitions selected, "
          f"cost {plan['total_selected_cost']}/{budget}")


if __name__ == "__main__":
    main()
