"""Multi-join optimization opportunity detection."""

from typing import List, Tuple
from .models import (
    ExecutionPlan,
    NodeType,
    MultiJoinOpportunity,
    MULTI_JOIN_ELIGIBLE_TYPES,
)
from .state_estimator import estimate_join_state_bytes


def find_cascaded_join_chains(plan: ExecutionPlan) -> List[List[int]]:
    """Find maximal chains of cascaded join nodes in the plan DAG."""
    join_ids = {nid for nid, n in plan.nodes.items() if n.type == NodeType.JOIN}

    # Build join-to-join parent/child maps
    children = {jid: [] for jid in join_ids}
    parents = {jid: [] for jid in join_ids}

    for jid in join_ids:
        for inp in plan.nodes[jid].inputs:
            if inp in join_ids:
                children[inp].append(jid)
                parents[jid].append(inp)

    # Chain roots: join nodes with no join-node parent
    roots = [jid for jid in join_ids if not parents[jid]]

    # Build maximal chains from each root via DFS
    chains = []

    def build_chains(node_id, current_chain):
        current_chain.append(node_id)
        join_children = children[node_id]
        if not join_children:
            # End of chain — only keep if length >= 2
            if len(current_chain) >= 2:
                chains.append(list(current_chain))
        else:
            for child in join_children:
                build_chains(child, current_chain)
        current_chain.pop()

    for root in roots:
        build_chains(root, [])

    return chains


def get_all_key_columns(plan: ExecutionPlan, join_node_id: int) -> set:
    """Get all join key column names for a join node."""
    node = plan.nodes[join_node_id]
    cols = set()
    for jk in node.join_keys:
        cols.add(jk.left_column)
        cols.add(jk.right_column)
    return cols


def check_multi_join_eligible(
    plan: ExecutionPlan, chain: List[int]
) -> Tuple[bool, str]:
    """Check if a cascaded join chain is eligible for multi-join."""
    if len(chain) < 2:
        return (False, "chain has fewer than 2 joins")

    # Check all joins are INNER or LEFT
    for jid in chain:
        node = plan.nodes[jid]
        if node.join_type not in MULTI_JOIN_ELIGIBLE_TYPES:
            return (
                False,
                f"join {jid} is {node.join_type.value}, not INNER/LEFT",
            )

    # Check for at least one common key column across all joins
    key_sets = [get_all_key_columns(plan, jid) for jid in chain]
    common = key_sets[0]
    for ks in key_sets[1:]:
        common = common & ks

    if not common:
        return (False, "no common join key across all joins in chain")

    # Return the lexicographically first common key
    return (True, sorted(common)[0])


def collect_leaf_source_ids(plan: ExecutionPlan, chain: List[int]) -> List[int]:
    """Collect all original source node IDs feeding into a join chain."""
    chain_set = set(chain)
    sources = set()

    def traverse(node_id):
        node = plan.nodes[node_id]
        if node.type == NodeType.SOURCE:
            sources.add(node_id)
        elif node_id in chain_set:
            # This is a join in our chain — recurse into its inputs
            for inp in node.inputs:
                traverse(inp)
        else:
            # Non-source, non-chain node (shouldn't happen in these plans,
            # but treat as a leaf)
            sources.add(node_id)

    for jid in chain:
        for inp in plan.nodes[jid].inputs:
            traverse(inp)

    return sorted(sources)


def compute_multi_join_state(plan: ExecutionPlan, source_ids: List[int]) -> int:
    """Compute total state for a multi-join operator (raw inputs only)."""
    ttl = plan.state_ttl_seconds
    total = 0
    for sid in source_ids:
        node = plan.nodes[sid]
        total += int(node.rate_per_second * ttl * node.avg_row_size_bytes)
    return total


def find_multi_join_opportunities(
    plan: ExecutionPlan,
) -> List[MultiJoinOpportunity]:
    """Find all multi-join optimization opportunities in the plan."""
    chains = find_cascaded_join_chains(plan)
    opportunities = []

    for chain in chains:
        eligible, key_or_reason = check_multi_join_eligible(plan, chain)
        if not eligible:
            continue

        source_ids = collect_leaf_source_ids(plan, chain)
        cascaded_state = sum(
            estimate_join_state_bytes(plan, jid) for jid in chain
        )
        multi_state = compute_multi_join_state(plan, source_ids)
        savings = cascaded_state - multi_state
        savings_pct = round(savings / cascaded_state * 100, 2)

        opportunities.append(
            MultiJoinOpportunity(
                join_ids=sorted(chain),
                common_key=key_or_reason,
                source_ids=source_ids,
                cascaded_state_bytes=cascaded_state,
                multi_join_state_bytes=multi_state,
                savings_bytes=savings,
                savings_percent=savings_pct,
            )
        )

    return opportunities
