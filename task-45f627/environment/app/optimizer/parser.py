"""Parser for Flink streaming execution plan JSON files."""

import json
from pathlib import Path
from typing import List
from .models import (
    ExecutionPlan, PlanNode, NodeType, JoinType, JoinKey
)


def parse_plan_file(filepath: str) -> ExecutionPlan:
    """Parse a JSON execution plan file into an ExecutionPlan object."""
    with open(filepath, "r") as f:
        data = json.load(f)

    plan = ExecutionPlan(
        plan_name=data["plan_name"],
        state_ttl_seconds=data["state_ttl_seconds"],
    )

    for node_data in data["nodes"]:
        node = PlanNode(
            id=node_data["id"],
            type=NodeType(node_data["type"]),
            name=node_data["name"],
            inputs=node_data.get("inputs", []),
        )

        if node.type == NodeType.SOURCE:
            node.rate_per_second = node_data["rate_per_second"]
            node.avg_row_size_bytes = node_data["avg_row_size_bytes"]

        elif node.type == NodeType.JOIN:
            node.join_type = JoinType(node_data["join_type"])
            node.join_keys = [
                JoinKey(left_column=k["left"], right_column=k["right"])
                for k in node_data["join_keys"]
            ]
            node.estimated_output_rate = node_data["estimated_output_rate"]
            node.estimated_output_row_size = node_data["estimated_output_row_size"]

        elif node.type == NodeType.ASYNC_ML_PREDICT:
            node.target_qps = node_data["target_qps"]
            node.p99_latency_seconds = node_data["p99_latency_seconds"]
            node.avg_request_size_bytes = node_data["avg_request_size_bytes"]
            node.max_ops_per_subtask = node_data["max_ops_per_subtask"]

        plan.nodes[node.id] = node

    return plan


def load_all_plans(plans_dir: str) -> List[ExecutionPlan]:
    """Load all JSON plan files from a directory, sorted by filename."""
    plans = []
    plans_path = Path(plans_dir)
    for filepath in sorted(plans_path.glob("*.json")):
        plans.append(parse_plan_file(str(filepath)))
    return plans
