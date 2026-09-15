"""Core streaming engine primitives for stateful stream processing.

Implements watermark tracking, keyed state management, and distributed
checkpoint coordination following the asynchronous barrier snapshotting
algorithm used in Apache Flink.
"""


import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class Transaction:
    """A financial transaction event in the stream."""
    account_id: int
    amount: float
    timestamp: int  # event time in milliseconds
    event_id: str = ""

    def __post_init__(self):
        if not self.event_id:
            self.event_id = f"txn-{self.account_id}-{self.timestamp}"


@dataclass
class FraudAlert:
    """Alert emitted when a suspicious transaction pattern is detected."""
    account_id: int
    pattern: str
    event_ids: List[str]
    timestamp: int


class WatermarkCombiner:
    """Combines watermarks from multiple parallel input channels.

    The combined watermark equals the MINIMUM across all channels,
    since event-time completeness can only be guaranteed up to the
    slowest upstream partition.
    """

    INITIAL_WATERMARK = -(10 ** 18)

    def __init__(self, num_channels: int):
        self.num_channels = num_channels
        self._channel_marks: Dict[int, int] = {
            i: self.INITIAL_WATERMARK for i in range(num_channels)
        }

    def update(self, channel_id: int, timestamp: int) -> int:
        if channel_id not in self._channel_marks:
            raise ValueError(f"Invalid channel ID: {channel_id}")
        self._channel_marks[channel_id] = timestamp
        return self._compute_combined()

    def get_combined(self) -> int:
        return self._compute_combined()

    def _compute_combined(self) -> int:
        return min(self._channel_marks.values())


class KeyedStateBackend:
    """Manages partitioned state for keyed stream operators.

    State is stored using composite keys of the form "key:state_name"
    to ensure per-key isolation.
    """

    def __init__(self):
        self._store: Dict[str, Any] = {}

    def get_state(self, key: Any, state_name: str, default: Any = None) -> Any:
        return self._store.get(f"{key}:{state_name}", default)

    def set_state(self, key: Any, state_name: str, value: Any) -> None:
        self._store[f"{key}:{state_name}"] = value

    def clear_state(self, key: Any, state_name: str) -> None:
        self._store.pop(f"{key}:{state_name}", None)

    def snapshot(self) -> Dict:
        return copy.deepcopy(self._store)

    def restore(self, snapshot: Dict) -> None:
        self._store = copy.deepcopy(snapshot)


class CheckpointCoordinator:
    """Coordinates distributed snapshots across all parallel tasks.

    Tracks acknowledgments using a set of task IDs to prevent
    duplicate acks from prematurely completing a checkpoint.
    """

    def __init__(self, task_ids: List[str]):
        self._task_ids = set(task_ids)
        self._num_tasks = len(self._task_ids)
        self._pending: Dict[int, Set[str]] = {}
        self._pending_states: Dict[int, Dict[str, Dict]] = {}
        self._completed: Dict[int, Dict[str, Dict]] = {}

    def trigger(self, checkpoint_id: int) -> None:
        self._pending[checkpoint_id] = set()
        self._pending_states[checkpoint_id] = {}

    def acknowledge(self, checkpoint_id: int, task_id: str,
                    state_snapshot: Dict) -> bool:
        if checkpoint_id not in self._pending:
            return False
        self._pending_states[checkpoint_id][task_id] = state_snapshot
        self._pending[checkpoint_id].add(task_id)
        if len(self._pending[checkpoint_id]) >= self._num_tasks:
            self._completed[checkpoint_id] = (
                self._pending_states.pop(checkpoint_id)
            )
            del self._pending[checkpoint_id]
            return True
        return False

    def get_latest_completed(self) -> Optional[Tuple[int, Dict[str, Dict]]]:
        if not self._completed:
            return None
        cp_id = max(self._completed.keys())
        return (cp_id, self._completed[cp_id])

    def is_pending(self, checkpoint_id: int) -> bool:
        return checkpoint_id in self._pending
