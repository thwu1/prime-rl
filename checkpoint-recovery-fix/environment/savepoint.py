"""Savepoint-based rescaling for the streaming pipeline."""


from typing import Any, Dict, List, Tuple

MAX_PARALLELISM = 128


def compute_key_group(key: Any, max_parallelism: int = MAX_PARALLELISM) -> int:
    """Map a key to a key-group index in [0, max_parallelism)."""
    raise NotImplementedError


def compute_key_group_range(
    operator_index: int,
    parallelism: int,
    max_parallelism: int = MAX_PARALLELISM,
) -> Tuple[int, int]:
    """Return the key-group range (start, end) for an operator."""
    raise NotImplementedError


def find_operator_for_key_group(
    key_group: int,
    parallelism: int,
    max_parallelism: int = MAX_PARALLELISM,
) -> int:
    """Return the operator index that owns a given key-group."""
    raise NotImplementedError


def redistribute_keyed_state(
    old_backend_states: List[Dict],
    old_parallelism: int,
    new_parallelism: int,
    max_parallelism: int = MAX_PARALLELISM,
) -> List[Dict]:
    """Redistribute keyed state across a different number of operators."""
    raise NotImplementedError


def create_savepoint(pipeline) -> Dict:
    """Create a savepoint from the pipeline's latest completed checkpoint."""
    raise NotImplementedError


def restore_pipeline_from_savepoint(
    savepoint: Dict,
    events: list,
    new_parallelism: int,
):
    """Restore a pipeline from a savepoint at a different parallelism."""
    raise NotImplementedError
