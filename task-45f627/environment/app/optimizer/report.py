"""Optimization report generation.

Generates a JSON report combining state estimates, multi-join opportunities,
and async capacity plans for all execution plans.

Output format:
{
    "plans": {
        "<plan_name>": {
            "total_join_state_bytes": <int>,
            "multi_join_opportunities": [
                {
                    "join_ids": [<int>, ...],
                    "common_key": "<string>",
                    "source_ids": [<int>, ...],
                    "cascaded_state_bytes": <int>,
                    "multi_join_state_bytes": <int>,
                    "savings_bytes": <int>,
                    "savings_percent": <float>
                }, ...
            ],
            "async_ml_predict": [
                {
                    "node_id": <int>,
                    "name": "<string>",
                    "required_queue_depth": <int>,
                    "min_parallelism": <int>,
                    "memory_per_subtask_bytes": <int>,
                    "total_async_memory_bytes": <int>
                }, ...
            ]
        }, ...
    }
}
"""

import json
from dataclasses import asdict
from typing import List
from pathlib import Path
from .models import ExecutionPlan, PlanReport
from .state_estimator import estimate_total_join_state
from .join_analyzer import find_multi_join_opportunities
from .capacity_planner import plan_async_capacity


def generate_plan_report(
    plan: ExecutionPlan,
    safety_factor: float = 1.2,
) -> PlanReport:
    """Generate optimization report for a single execution plan.

    Combines:
    - Total join state estimation
    - Multi-join opportunity detection
    - Async ML_PREDICT capacity planning

    Args:
        plan: The execution plan to analyze
        safety_factor: Safety factor for async capacity planning

    Returns:
        PlanReport with all analysis results
    """
    raise NotImplementedError("Implement generate_plan_report")


def generate_full_report(
    plans: List[ExecutionPlan],
    safety_factor: float = 1.2,
) -> dict:
    """Generate optimization reports for all plans.

    Returns a JSON-serializable dict keyed by plan name.

    Args:
        plans: List of execution plans
        safety_factor: Safety factor for async capacity planning

    Returns:
        Dict with structure shown in module docstring
    """
    raise NotImplementedError("Implement generate_full_report")


def write_report(report: dict, output_path: str) -> None:
    """Write the report dict to a JSON file, creating parent dirs if needed.

    Args:
        report: The JSON-serializable report dict
        output_path: File path to write to
    """
    raise NotImplementedError("Implement write_report")
