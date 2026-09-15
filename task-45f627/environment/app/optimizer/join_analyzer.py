"""Multi-join optimization opportunity detection for Flink streaming plans.

Apache Flink 2.1 introduces the StreamingMultiJoinOperator that replaces
cascaded binary streaming joins with a single multi-join operator,
eliminating intermediate result state.

Eligibility criteria (per Flink 2.1 release notes):
1. The chain must contain at least 2 cascaded join nodes (joining 3+ tables)
2. All joins in the chain must be INNER or LEFT (not RIGHT or FULL)
3. All joins must share at least one common join key column name

State savings model:
- Cascaded binary joins: each join stores state for both its inputs,
  including intermediate join results from upstream joins
- Multi-way join: stores only the original source input states,
  with zero intermediate result state

Reference: "Multiple Regular Joins" feature in Apache Flink 2.1,
enabled via SET 'table.optimizer.multi-join.enabled' = 'true'.
Presented at Flink Forward Barcelona 2025.
"""

from typing import List, Tuple
from .models import (
    ExecutionPlan, PlanNode, NodeType, JoinType,
    MultiJoinOpportunity, MULTI_JOIN_ELIGIBLE_TYPES
)
from .state_estimator import estimate_join_state_bytes, get_node_effective_rate_and_size


def find_cascaded_join_chains(plan: ExecutionPlan) -> List[List[int]]:
    """Find maximal chains of cascaded join nodes in the plan DAG.

    A cascaded join chain is a sequence [J1, J2, ..., Jn] where each
    join Jk's output feeds as one input into join J(k+1). The chain
    is maximal — it cannot be extended further in either direction.

    Algorithm:
    1. Identify all join nodes
    2. Build a directed graph of join-to-join edges: if join B has
       join A as one of its inputs, add edge A -> B
    3. Find all "root" joins (no join parent) and trace maximal paths

    Args:
        plan: The execution plan

    Returns:
        List of chains, each a list of join node IDs in topological
        (upstream to downstream) order. Only chains with length >= 2
        are included.
    """
    raise NotImplementedError("Implement find_cascaded_join_chains")


def get_all_key_columns(plan: ExecutionPlan, join_node_id: int) -> set:
    """Get all join key column names (both left and right) for a join node.

    Args:
        plan: The execution plan
        join_node_id: The join node ID

    Returns:
        Set of column name strings from all join keys
    """
    raise NotImplementedError("Implement get_all_key_columns")


def check_multi_join_eligible(
    plan: ExecutionPlan, chain: List[int]
) -> Tuple[bool, str]:
    """Check if a cascaded join chain is eligible for multi-join optimization.

    Criteria:
    1. Chain length >= 2 (at least 2 join nodes, joining 3+ tables)
    2. All join nodes have join_type in MULTI_JOIN_ELIGIBLE_TYPES
    3. There exists at least one key column name that appears in every
       join node's key set (intersection of all key column sets is non-empty)

    Args:
        plan: The execution plan
        chain: List of join node IDs forming a cascaded chain

    Returns:
        (True, common_key_name) if eligible — where common_key_name is the
            lexicographically first common key if multiple exist
        (False, reason_string) if not eligible
    """
    raise NotImplementedError("Implement check_multi_join_eligible")


def collect_leaf_source_ids(plan: ExecutionPlan, chain: List[int]) -> List[int]:
    """Collect all original source node IDs feeding into a join chain.

    Traverse the chain's input tree: for each join in the chain, examine
    its inputs. If an input is another join in the chain, recurse into
    that join's inputs. If an input is a Source node (or any node outside
    the chain), record its ID.

    Args:
        plan: The execution plan
        chain: List of join node IDs

    Returns:
        Sorted list of unique source node IDs
    """
    raise NotImplementedError("Implement collect_leaf_source_ids")


def compute_multi_join_state(plan: ExecutionPlan, source_ids: List[int]) -> int:
    """Compute the total state for a multi-join operator.

    Multi-way join stores only the raw source input states (no intermediate
    results). For each source node:
        source_state = rate_per_second * state_ttl_seconds * avg_row_size_bytes

    Args:
        plan: The execution plan
        source_ids: List of source node IDs

    Returns:
        Total multi-join state in bytes
    """
    raise NotImplementedError("Implement compute_multi_join_state")


def find_multi_join_opportunities(plan: ExecutionPlan) -> List[MultiJoinOpportunity]:
    """Find all multi-join optimization opportunities in the plan.

    Steps:
    1. Find cascaded join chains via find_cascaded_join_chains()
    2. Check each chain for eligibility via check_multi_join_eligible()
    3. For eligible chains, collect source IDs and compute state savings

    Savings calculation:
        cascaded_state = sum of estimate_join_state_bytes() for each join in chain
        multi_join_state = compute_multi_join_state() for the chain's sources
        savings = cascaded_state - multi_join_state
        savings_percent = round(savings / cascaded_state * 100, 2)

    Args:
        plan: The execution plan

    Returns:
        List of MultiJoinOpportunity objects for all eligible chains
    """
    raise NotImplementedError("Implement find_multi_join_opportunities")
