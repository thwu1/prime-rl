"""Async ML_PREDICT capacity planning using Little's Law.

For Flink SQL AI functions (ML_PREDICT with async execution),
capacity planning uses Little's Law to determine the required
concurrency and resources:

    L = lambda * W

Where:
    L = required queue depth (number of concurrent pending requests)
    lambda = arrival rate (target QPS)
    W = average service time (use p99 latency for safety margin)

With a configurable safety factor:
    L_safe = ceil(lambda * W * safety_factor)

Resource requirements:
    min_parallelism = ceil(L_safe / max_ops_per_subtask)
    memory_per_subtask = max_ops_per_subtask * avg_request_size_bytes
    total_async_memory = L_safe * avg_request_size_bytes

Reference: "Optimizing Flink SQL AI Functions: Async Tuning &
Resource Planning for Performance" presentation at Flink Forward
Barcelona 2025, by Lincoln (Alibaba Cloud / Apache Flink PMC).
"""

import math
from typing import List
from .models import ExecutionPlan, PlanNode, NodeType, AsyncMLPredictConfig


def compute_async_config(
    node: PlanNode,
    safety_factor: float = 1.2,
) -> AsyncMLPredictConfig:
    """Compute optimal async ML_PREDICT configuration using Little's Law.

    Formulas:
        required_queue_depth = ceil(target_qps * p99_latency_seconds * safety_factor)
        min_parallelism = ceil(required_queue_depth / max_ops_per_subtask)
        memory_per_subtask = max_ops_per_subtask * avg_request_size_bytes
        total_async_memory = required_queue_depth * avg_request_size_bytes

    Args:
        node: The AsyncMLPredict plan node with target_qps,
              p99_latency_seconds, avg_request_size_bytes, and
              max_ops_per_subtask fields populated
        safety_factor: Multiplier for queue depth (default 1.2)

    Returns:
        AsyncMLPredictConfig with all computed values
    """
    raise NotImplementedError("Implement compute_async_config")


def plan_async_capacity(
    plan: ExecutionPlan,
    safety_factor: float = 1.2,
) -> List[AsyncMLPredictConfig]:
    """Find all AsyncMLPredict nodes and compute their configurations.

    Iterates over all nodes in the plan, finds those with
    type == ASYNC_ML_PREDICT, and computes async configuration
    for each using compute_async_config().

    Args:
        plan: The execution plan
        safety_factor: Multiplier for queue depth

    Returns:
        List of AsyncMLPredictConfig for each AsyncMLPredict node
    """
    raise NotImplementedError("Implement plan_async_capacity")
