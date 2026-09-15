"""Backfill execution planner — solution implementation."""

from typing import Dict, List
from dataclasses import dataclass, field


@dataclass
class AssetNode:
    key: str
    partition_keys: List[str]
    dependencies: List[str] = field(default_factory=list)
    sequential: bool = False


@dataclass
class ExecutionStep:
    asset_key: str
    partition_key: str
    priority: int


def compute_topological_order(nodes: Dict[str, AssetNode]) -> Dict[str, int]:
    in_degree: Dict[str, int] = {key: 0 for key in nodes}
    adj: Dict[str, List[str]] = {key: [] for key in nodes}

    for key, node in nodes.items():
        for dep in node.dependencies:
            adj[dep].append(key)
            in_degree[key] += 1

    queue = sorted([key for key in nodes if in_degree[key] == 0])
    order: Dict[str, int] = {}
    idx = 0

    while queue:
        key = queue.pop(0)
        order[key] = idx
        idx += 1
        for neighbor in sorted(adj[key]):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
        queue.sort()

    if len(order) != len(nodes):
        raise ValueError("Dependency graph contains a cycle")

    return order


def build_execution_plan(
    nodes: Dict[str, AssetNode],
    concurrency_limit: int = 1,
) -> List[List[ExecutionStep]]:
    if not nodes:
        return []

    topo_order = compute_topological_order(nodes)

    # Generate all steps sorted by priority
    all_steps: List[ExecutionStep] = []
    for key, node in nodes.items():
        for part_idx, part_key in enumerate(node.partition_keys):
            priority = topo_order[key] * 1000 + part_idx
            all_steps.append(ExecutionStep(
                asset_key=key,
                partition_key=part_key,
                priority=priority,
            ))

    all_steps.sort(key=lambda s: s.priority)

    if not all_steps:
        return []

    waves: List[List[ExecutionStep]] = []
    completed: set = set()  # (asset_key, partition_key) pairs from prior waves
    remaining = list(all_steps)

    while remaining:
        wave: List[ExecutionStep] = []
        still_remaining: List[ExecutionStep] = []

        for step in remaining:
            if len(wave) >= concurrency_limit:
                still_remaining.append(step)
                continue

            node = nodes[step.asset_key]
            can_schedule = True

            # Check: all upstream assets' partitions must be completed
            for dep in node.dependencies:
                dep_node = nodes[dep]
                for pk in dep_node.partition_keys:
                    if (dep, pk) not in completed:
                        can_schedule = False
                        break
                if not can_schedule:
                    break

            # Check: sequential ordering within asset
            if can_schedule and node.sequential:
                part_idx = node.partition_keys.index(step.partition_key)
                if part_idx > 0:
                    prev_pk = node.partition_keys[part_idx - 1]
                    if (step.asset_key, prev_pk) not in completed:
                        can_schedule = False

            if can_schedule:
                wave.append(step)
            else:
                still_remaining.append(step)

        if not wave:
            raise ValueError("Cannot make progress — possible deadlock in execution plan")

        for step in wave:
            completed.add((step.asset_key, step.partition_key))
        waves.append(wave)
        remaining = still_remaining

    return waves
