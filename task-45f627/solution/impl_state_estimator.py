"""State cost estimation for Flink streaming join operators."""

from .models import ExecutionPlan, NodeType


def get_node_effective_rate_and_size(plan: ExecutionPlan, node_id: int) -> tuple:
    """Get the effective output rate and row size for a node."""
    node = plan.nodes[node_id]

    if node.type == NodeType.SOURCE:
        return (node.rate_per_second, node.avg_row_size_bytes)
    elif node.type == NodeType.JOIN:
        return (node.estimated_output_rate, node.estimated_output_row_size)
    elif node.type in (NodeType.ASYNC_ML_PREDICT, NodeType.CALC):
        if node.inputs:
            return get_node_effective_rate_and_size(plan, node.inputs[0])
        raise ValueError(f"Node {node_id} ({node.type}) has no inputs")
    else:
        raise ValueError(f"Cannot resolve rate/size for node type {node.type}")


def estimate_join_state_bytes(plan: ExecutionPlan, join_node_id: int) -> int:
    """Estimate the total state size in bytes for a single streaming join node."""
    node = plan.nodes[join_node_id]
    assert node.type == NodeType.JOIN, f"Node {join_node_id} is not a Join"

    ttl = plan.state_ttl_seconds
    left_id = node.inputs[0]
    right_id = node.inputs[1]

    left_rate, left_size = get_node_effective_rate_and_size(plan, left_id)
    right_rate, right_size = get_node_effective_rate_and_size(plan, right_id)

    left_state = int(left_rate * ttl * left_size)
    right_state = int(right_rate * ttl * right_size)

    return left_state + right_state


def estimate_total_join_state(plan: ExecutionPlan) -> int:
    """Compute the sum of state estimates for all join nodes in the plan."""
    total = 0
    for node in plan.nodes.values():
        if node.type == NodeType.JOIN:
            total += estimate_join_state_bytes(plan, node.id)
    return total
