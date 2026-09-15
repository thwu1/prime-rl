"""Optimization report generation."""

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
    """Generate optimization report for a single execution plan."""
    return PlanReport(
        plan_name=plan.plan_name,
        total_join_state_bytes=estimate_total_join_state(plan),
        multi_join_opportunities=find_multi_join_opportunities(plan),
        async_ml_predict=plan_async_capacity(plan, safety_factor),
    )


def generate_full_report(
    plans: List[ExecutionPlan],
    safety_factor: float = 1.2,
) -> dict:
    """Generate optimization reports for all plans."""
    result = {"plans": {}}
    for plan in plans:
        pr = generate_plan_report(plan, safety_factor)
        result["plans"][pr.plan_name] = {
            "total_join_state_bytes": pr.total_join_state_bytes,
            "multi_join_opportunities": [
                asdict(o) for o in pr.multi_join_opportunities
            ],
            "async_ml_predict": [asdict(a) for a in pr.async_ml_predict],
        }
    return result


def write_report(report: dict, output_path: str) -> None:
    """Write the report dict to a JSON file."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
