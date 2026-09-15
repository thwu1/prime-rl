"""Backfill execution planner.

Generates ordered execution plans for backfilling partitioned assets,
respecting dependency and ordering constraints.
"""

from typing import Dict, List
from dataclasses import dataclass, field


@dataclass
class AssetNode:
    """Node in the asset dependency graph."""

    key: str
    partition_keys: List[str]
    dependencies: List[str] = field(default_factory=list)
    sequential: bool = False


@dataclass
class ExecutionStep:
    """A single step in the execution plan."""

    asset_key: str
    partition_key: str
    priority: int


def compute_topological_order(nodes: Dict[str, AssetNode]) -> Dict[str, int]:
    """Compute a topological ordering of asset nodes."""
    in_degree = {key: 0 for key in nodes}
    adj = {key: [] for key in nodes}
    for key, node in nodes.items():
        for dep in node.dependencies:
            adj[dep].append(key)
            in_degree[key] += 1
    queue = sorted(k for k in nodes if in_degree[k] == 0)
    order = {}
    idx = 0
    while queue:
        key = queue.pop(0)
        order[key] = idx
        idx += 1
        for nb in sorted(adj[key]):
            in_degree[nb] -= 1
            if in_degree[nb] == 0:
                queue.append(nb)
        queue.sort()
    if len(order) != len(nodes):
        raise ValueError("Dependency graph contains a cycle")
    return order


def build_execution_plan(
    nodes: Dict[str, AssetNode], concurrency_limit: int = 1
) -> List[List[ExecutionStep]]:
    """Build a wave-based execution plan for backfilling assets."""
    if not nodes:
        return []
    topo_order = compute_topological_order(nodes)
    all_steps = []
    for key, node in nodes.items():
        for pi, pk in enumerate(node.partition_keys):
            all_steps.append(
                ExecutionStep(
                    asset_key=key,
                    partition_key=pk,
                    priority=topo_order[key] * 1000 + pi,
                )
            )
    all_steps.sort(key=lambda s: s.priority)
    if not all_steps:
        return []
    waves = []
    completed = set()
    remaining = list(all_steps)
    while remaining:
        wave = []
        still_remaining = []
        for step in remaining:
            if len(wave) >= concurrency_limit:
                still_remaining.append(step)
                continue
            node = nodes[step.asset_key]
            can_schedule = True
            for dep in node.dependencies:
                dep_node = nodes[dep]
                for dpk in dep_node.partition_keys:
                    if (dep, dpk) not in completed:
                        can_schedule = False
                        break
                if not can_schedule:
                    break
            if can_schedule and node.sequential:
                pi = node.partition_keys.index(step.partition_key)
                if pi > 0:
                    prev_pk = node.partition_keys[pi - 1]
                    if (step.asset_key, prev_pk) not in completed:
                        can_schedule = False
            if can_schedule:
                wave.append(step)
            else:
                still_remaining.append(step)
        if not wave:
            raise ValueError("Cannot make progress -- possible deadlock")
        for step in wave:
            completed.add((step.asset_key, step.partition_key))
        waves.append(wave)
        remaining = still_remaining
    return waves
