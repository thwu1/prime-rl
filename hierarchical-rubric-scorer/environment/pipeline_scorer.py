"""Hierarchical scoring with dependency resolution."""


def build_criteria_graph(criteria_map):
    """Build topological ordering of criteria (children before parents)."""
    visited = set()
    order = []

    def visit(node_id):
        if node_id in visited:
            return
        visited.add(node_id)
        node = criteria_map[node_id]
        for child_id in node.get("children", []):
            visit(child_id)
        for dep_id in node.get("dependencies", []):
            visit(dep_id)
        order.append(node_id)

    for crit_id in criteria_map:
        visit(crit_id)

    return order


def resolve_scores(aggregated, criteria_map, topo_order, sample_ids, threshold):
    """Process criteria in topological order: compute aggregates and resolve dependencies."""
    for sample_id in sample_ids:
        for crit_id in topo_order:
            crit = criteria_map[crit_id]

            if crit["score_type"] == "aggregate":
                children = crit.get("children", [])
                if children:
                    contributing = [
                        c for c in children
                        if aggregated.get((sample_id, c), 0.0) > 0.0
                    ]
                    if contributing:
                        total_weight = sum(
                            criteria_map[c]["weight"] for c in contributing
                        )
                        score = sum(
                            criteria_map[c]["weight"] * aggregated[(sample_id, c)]
                            for c in contributing
                        ) / total_weight
                    else:
                        score = 0.0
                else:
                    score = 0.0
                aggregated[(sample_id, crit_id)] = score

            for dep_id in crit.get("dependencies", []):
                if aggregated.get((sample_id, dep_id), 0.0) < threshold:
                    aggregated[(sample_id, crit_id)] = 0.0
                    break

    return aggregated
