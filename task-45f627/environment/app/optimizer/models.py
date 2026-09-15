"""Data models for Flink streaming execution plan optimization.

These models represent Flink streaming execution plan nodes, join strategies,
and optimization analysis results. Based on Apache Flink 2.1 streaming join
semantics and the StreamingMultiJoinOperator introduced in FLIP-415.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum


class NodeType(Enum):
    SOURCE = "Source"
    JOIN = "Join"
    ASYNC_ML_PREDICT = "AsyncMLPredict"
    CALC = "Calc"
    SINK = "Sink"


class JoinType(Enum):
    INNER = "INNER"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    FULL = "FULL"


# Join types eligible for multi-join optimization (per Flink 2.1 release notes:
# "pipelines with multiple INNER/LEFT joins that share at least one common join key")
MULTI_JOIN_ELIGIBLE_TYPES = {JoinType.INNER, JoinType.LEFT}


@dataclass
class JoinKey:
    left_column: str
    right_column: str


@dataclass
class PlanNode:
    id: int
    type: NodeType
    name: str
    inputs: List[int] = field(default_factory=list)
    # Source-specific fields
    rate_per_second: Optional[float] = None
    avg_row_size_bytes: Optional[int] = None
    # Join-specific fields
    join_type: Optional[JoinType] = None
    join_keys: Optional[List[JoinKey]] = None
    estimated_output_rate: Optional[float] = None
    estimated_output_row_size: Optional[int] = None
    # AsyncMLPredict-specific fields
    target_qps: Optional[float] = None
    p99_latency_seconds: Optional[float] = None
    avg_request_size_bytes: Optional[int] = None
    max_ops_per_subtask: Optional[int] = None


@dataclass
class ExecutionPlan:
    plan_name: str
    state_ttl_seconds: int
    nodes: Dict[int, PlanNode] = field(default_factory=dict)


@dataclass
class MultiJoinOpportunity:
    join_ids: List[int]
    common_key: str
    source_ids: List[int]
    cascaded_state_bytes: int
    multi_join_state_bytes: int
    savings_bytes: int
    savings_percent: float


@dataclass
class AsyncMLPredictConfig:
    node_id: int
    name: str
    required_queue_depth: int
    min_parallelism: int
    memory_per_subtask_bytes: int
    total_async_memory_bytes: int


@dataclass
class PlanReport:
    plan_name: str
    total_join_state_bytes: int
    multi_join_opportunities: List[MultiJoinOpportunity]
    async_ml_predict: List[AsyncMLPredictConfig]
