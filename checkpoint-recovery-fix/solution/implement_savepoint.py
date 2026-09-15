#!/usr/bin/env python3
"""Implementation of savepoint-based rescaling for the streaming pipeline.

Implements key-group-based state partitioning following Apache Flink's
KeyGroupRangeAssignment model, with state redistribution, savepoint
creation, and pipeline restoration at different parallelism.
"""


import copy
from typing import Any, Dict, List, Tuple

from pipeline import FraudDetectionPipeline
from streaming import Transaction

MAX_PARALLELISM = 128


def _murmur_finalize(h: int) -> int:
    """Murmur3-style finalization mix for integer hashing."""
    h = h & 0xFFFFFFFF
    h ^= h >> 16
    h = (h * 0x85ebca6b) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 0xc2b2ae35) & 0xFFFFFFFF
    h ^= h >> 16
    return h


def compute_key_group(key: Any, max_parallelism: int = MAX_PARALLELISM) -> int:
    """Map a key to a key-group index in [0, max_parallelism)."""
    if isinstance(key, int):
        h = _murmur_finalize(key & 0xFFFFFFFF)
    else:
        h = 0
        for ch in str(key):
            h = ((h * 31) + ord(ch)) & 0xFFFFFFFF
        h = _murmur_finalize(h)
    return h % max_parallelism


def compute_key_group_range(
    operator_index: int,
    parallelism: int,
    max_parallelism: int = MAX_PARALLELISM,
) -> Tuple[int, int]:
    """Return (start_inclusive, end_exclusive) key-group range for an operator.

    Distributes max_parallelism key-groups as evenly as possible across
    parallelism operators. The first (max_parallelism % parallelism)
    operators each get one extra key-group.
    """
    groups_per_op = max_parallelism // parallelism
    remainder = max_parallelism % parallelism

    if operator_index < remainder:
        start = operator_index * (groups_per_op + 1)
        end = start + groups_per_op + 1
    else:
        start = remainder * (groups_per_op + 1) + (operator_index - remainder) * groups_per_op
        end = start + groups_per_op

    return (start, end)


def find_operator_for_key_group(
    key_group: int,
    parallelism: int,
    max_parallelism: int = MAX_PARALLELISM,
) -> int:
    """Return the operator index that owns the given key-group.

    Performs the reverse lookup of compute_key_group_range using
    arithmetic instead of iterating all ranges.
    """
    groups_per_op = max_parallelism // parallelism
    remainder = max_parallelism % parallelism

    boundary = remainder * (groups_per_op + 1)

    if key_group < boundary:
        return key_group // (groups_per_op + 1)
    else:
        return remainder + (key_group - boundary) // groups_per_op


def _parse_key_from_composite(composite_key: str) -> Any:
    """Extract the original key from a composite 'key:state_name' string."""
    key_str = composite_key.split(":", 1)[0]
    try:
        return int(key_str)
    except (ValueError, TypeError):
        return key_str


def redistribute_keyed_state(
    old_backend_states: List[Dict],
    old_parallelism: int,
    new_parallelism: int,
    max_parallelism: int = MAX_PARALLELISM,
) -> List[Dict]:
    """Redistribute keyed state across a different number of operators."""
    new_states: List[Dict] = [{} for _ in range(new_parallelism)]

    for old_state in old_backend_states:
        for composite_key, value in old_state.items():
            key = _parse_key_from_composite(composite_key)
            kg = compute_key_group(key, max_parallelism)
            new_idx = find_operator_for_key_group(kg, new_parallelism, max_parallelism)
            new_states[new_idx][composite_key] = copy.deepcopy(value)

    return new_states


def _key_group_routing(txn: Transaction, parallelism: int) -> int:
    """Route a transaction to an operator using key-group assignment."""
    kg = compute_key_group(txn.account_id)
    return find_operator_for_key_group(kg, parallelism)


def create_savepoint(pipeline) -> Dict:
    """Create a savepoint from the pipeline's latest completed checkpoint."""
    result = pipeline.coordinator.get_latest_completed()
    if result is None:
        raise RuntimeError("No completed checkpoint available for savepoint")

    cp_id, states = result

    source_state = states[pipeline.source.task_id]
    detector_states = []
    for det in pipeline.detectors:
        detector_states.append(states[det.task_id])

    alert_count = sum(ds.get("num_alerts", 0) for ds in detector_states)

    return {
        "source": copy.deepcopy(source_state),
        "detectors": copy.deepcopy(detector_states),
        "alerts": copy.deepcopy(pipeline.alerts[:alert_count]),
        "parallelism": pipeline.parallelism,
        "checkpoint_id": cp_id,
    }


def restore_pipeline_from_savepoint(
    savepoint: Dict,
    events: list,
    new_parallelism: int,
) -> FraudDetectionPipeline:
    """Restore a FraudDetectionPipeline from a savepoint at new parallelism."""
    old_parallelism = savepoint["parallelism"]

    old_backend_states = [ds["backend"] for ds in savepoint["detectors"]]

    new_backend_states = redistribute_keyed_state(
        old_backend_states, old_parallelism, new_parallelism
    )

    pipeline = FraudDetectionPipeline(
        events,
        parallelism=new_parallelism,
        routing_fn=_key_group_routing,
    )

    pipeline.source.restore(savepoint["source"])

    min_watermark = min(
        (ds.get("watermark", -(10 ** 18)) for ds in savepoint["detectors"]),
        default=-(10 ** 18),
    )

    for i, det in enumerate(pipeline.detectors):
        det.state.restore(new_backend_states[i])
        det.watermark = min_watermark

    pipeline.alerts = copy.deepcopy(savepoint["alerts"])

    return pipeline
