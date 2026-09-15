"""State cost estimation for Flink streaming join operators.

In Flink streaming joins, each join node maintains state for both its
left and right inputs. The state size for each side is determined by
the input rate, the state time-to-live (TTL), and the average row size:

    state_bytes = input_rate_per_sec * state_ttl_seconds * avg_row_size_bytes

For cascaded binary joins where one join's output feeds into the next
join's input, the effective "input rate" of the downstream join's left
side is the upstream join's estimated_output_rate, and the effective
"row size" is the upstream join's estimated_output_row_size.

A join node always has exactly two inputs: inputs[0] is the left side
and inputs[1] is the right side.

Reference: Apache Flink 2.1 streaming join state management,
as presented at Flink Forward Barcelona 2025.
"""

from .models import ExecutionPlan, NodeType


def get_node_effective_rate_and_size(plan: ExecutionPlan, node_id: int) -> tuple:
    """Get the effective output rate (rows/sec) and row size (bytes) for a node.

    Resolution rules:
    - Source nodes: return (rate_per_second, avg_row_size_bytes)
    - Join nodes: return (estimated_output_rate, estimated_output_row_size)
    - AsyncMLPredict/Calc nodes: propagate from the single input node (inputs[0])

    Args:
        plan: The execution plan containing all nodes
        node_id: The node ID to resolve

    Returns:
        Tuple of (rate_per_second: float, avg_row_size_bytes: int)

    Raises:
        ValueError: If the node type cannot be resolved
    """
    raise NotImplementedError("Implement get_node_effective_rate_and_size")


def estimate_join_state_bytes(plan: ExecutionPlan, join_node_id: int) -> int:
    """Estimate the total state size in bytes for a single streaming join node.

    A streaming join maintains state for both inputs:
        state = (left_rate * ttl * left_row_size) + (right_rate * ttl * right_row_size)

    Where:
        - left input is node.inputs[0], right input is node.inputs[1]
        - ttl is plan.state_ttl_seconds
        - rates and sizes are resolved via get_node_effective_rate_and_size()

    Args:
        plan: The execution plan
        join_node_id: The ID of the join node to estimate

    Returns:
        Total state size in bytes (as integer, using int() truncation)
    """
    raise NotImplementedError("Implement estimate_join_state_bytes")


def estimate_total_join_state(plan: ExecutionPlan) -> int:
    """Compute the sum of state estimates for all join nodes in the plan.

    Iterates over all nodes in the plan, finds those with type == JOIN,
    and sums their individual state estimates.

    Args:
        plan: The execution plan

    Returns:
        Total state across all joins in bytes
    """
    raise NotImplementedError("Implement estimate_total_join_state")
