"""Async ML_PREDICT capacity planning using Little's Law."""

import math
from typing import List
from .models import ExecutionPlan, PlanNode, NodeType, AsyncMLPredictConfig


def compute_async_config(
    node: PlanNode,
    safety_factor: float = 1.2,
) -> AsyncMLPredictConfig:
    """Compute optimal async ML_PREDICT configuration using Little's Law."""
    L = math.ceil(node.target_qps * node.p99_latency_seconds * safety_factor)
    min_par = math.ceil(L / node.max_ops_per_subtask)
    mem_per = node.max_ops_per_subtask * node.avg_request_size_bytes
    total_mem = L * node.avg_request_size_bytes

    return AsyncMLPredictConfig(
        node_id=node.id,
        name=node.name,
        required_queue_depth=L,
        min_parallelism=min_par,
        memory_per_subtask_bytes=mem_per,
        total_async_memory_bytes=total_mem,
    )


def plan_async_capacity(
    plan: ExecutionPlan,
    safety_factor: float = 1.2,
) -> List[AsyncMLPredictConfig]:
    """Find all AsyncMLPredict nodes and compute their configurations."""
    configs = []
    for node in plan.nodes.values():
        if node.type == NodeType.ASYNC_ML_PREDICT:
            configs.append(compute_async_config(node, safety_factor))
    return configs
