"""Streaming fraud detection pipeline with checkpoint-recovery support.

Architecture::

    TransactionSource
        -> partition(account_id)
        -> FraudDetector[0 .. N-1]
        -> output alerts

Supports custom routing via an optional routing_fn parameter, enabling
key-group-based partitioning for savepoint rescaling.
"""


from typing import List, Dict, Optional, Callable
from streaming import (
    Transaction, FraudAlert, WatermarkCombiner,
    KeyedStateBackend, CheckpointCoordinator,
)


class TransactionSource:
    """Reads transaction events sequentially from an in-memory log."""

    def __init__(self, events: List[Transaction], task_id: str = "source-0"):
        self.events = events
        self.task_id = task_id
        self._offset = 0

    def emit_next(self) -> Optional[Transaction]:
        if self._offset >= len(self.events):
            return None
        event = self.events[self._offset]
        self._offset += 1
        return event

    @property
    def current_watermark(self) -> int:
        if self._offset == 0:
            return -(10 ** 18)
        return self.events[self._offset - 1].timestamp

    def snapshot(self) -> Dict:
        return {"offset": self._offset}

    def restore(self, state: Dict) -> None:
        self._offset = state["offset"]


class FraudDetector:
    """Stateful keyed operator that detects fraud patterns per account.

    Detection rule -- small-then-large:
        A transaction with amount < SMALL_THRESHOLD immediately followed
        (within WINDOW_MS event-time milliseconds) by a transaction with
        amount > LARGE_THRESHOLD on the same account triggers a FraudAlert.
    """

    SMALL_THRESHOLD = 1.00
    LARGE_THRESHOLD = 500.00
    WINDOW_MS = 60_000

    def __init__(self, task_id: str):
        self.task_id = task_id
        self.state = KeyedStateBackend()
        self.watermark = -(10 ** 18)
        self._alert_log: List[FraudAlert] = []

    def process(self, txn: Transaction) -> Optional[FraudAlert]:
        acct = txn.account_id
        prior_small = self.state.get_state(acct, "pending_small")

        if prior_small is not None:
            elapsed = txn.timestamp - prior_small["ts"]
            if txn.amount > self.LARGE_THRESHOLD and elapsed <= self.WINDOW_MS:
                alert = FraudAlert(
                    account_id=acct,
                    pattern="small-then-large",
                    event_ids=[prior_small["eid"], txn.event_id],
                    timestamp=txn.timestamp,
                )
                self._alert_log.append(alert)
                self.state.clear_state(acct, "pending_small")
                return alert
            if elapsed > self.WINDOW_MS:
                self.state.clear_state(acct, "pending_small")

        if txn.amount < self.SMALL_THRESHOLD:
            self.state.set_state(acct, "pending_small", {
                "eid": txn.event_id,
                "ts": txn.timestamp,
            })

        return None

    def advance_watermark(self, wm: int) -> None:
        self.watermark = wm

    def snapshot(self) -> Dict:
        return {
            "backend": self.state.snapshot(),
            "watermark": self.watermark,
            "num_alerts": len(self._alert_log),
        }

    def restore(self, state: Dict) -> None:
        self.state.restore(state["backend"])
        self.watermark = state["watermark"]
        self._alert_log = self._alert_log[:state["num_alerts"]]


class FraudDetectionPipeline:
    """End-to-end fraud detection pipeline with checkpointing.

    Partitions incoming transactions by account_id across
    ``parallelism`` FraudDetector instances. Supports custom routing
    via ``routing_fn(txn, parallelism) -> int`` for key-group-based
    partitioning during savepoint rescaling.
    """

    def __init__(self, events: List[Transaction], parallelism: int = 2,
                 routing_fn: Optional[Callable] = None):
        self.source = TransactionSource(events)
        self.parallelism = parallelism
        self.detectors = [
            FraudDetector(task_id=f"detector-{i}")
            for i in range(parallelism)
        ]
        self.wm_combiners = [
            WatermarkCombiner(num_channels=1) for _ in range(parallelism)
        ]
        all_task_ids = (
            [self.source.task_id]
            + [d.task_id for d in self.detectors]
        )
        self.coordinator = CheckpointCoordinator(all_task_ids)
        self.alerts: List[FraudAlert] = []
        self._cp_counter = 0
        self._routing_fn = routing_fn

    def _route(self, txn: Transaction) -> int:
        if self._routing_fn is not None:
            return self._routing_fn(txn, self.parallelism)
        return txn.account_id % self.parallelism

    def run(self, checkpoint_interval: int = 0) -> List[FraudAlert]:
        events_processed = 0
        while True:
            txn = self.source.emit_next()
            if txn is None:
                break
            part = self._route(txn)
            det = self.detectors[part]
            wm = self.source.current_watermark
            combined = self.wm_combiners[part].update(0, wm)
            det.advance_watermark(combined)
            alert = det.process(txn)
            if alert:
                self.alerts.append(alert)
            events_processed += 1
            if (checkpoint_interval > 0
                    and events_processed % checkpoint_interval == 0):
                self._cp_counter += 1
                self._checkpoint(self._cp_counter)
        return self.alerts

    def _checkpoint(self, cp_id: int) -> None:
        self.coordinator.trigger(cp_id)
        src_state = self.source.snapshot()
        self.coordinator.acknowledge(cp_id, self.source.task_id, src_state)
        for det in self.detectors:
            det_state = det.snapshot()
            self.coordinator.acknowledge(cp_id, det.task_id, det_state)

    def fail_and_recover(self) -> None:
        result = self.coordinator.get_latest_completed()
        if result is None:
            raise RuntimeError("No completed checkpoint for recovery")
        cp_id, states = result
        self.source.restore(states[self.source.task_id])
        for det in self.detectors:
            if det.task_id in states:
                det.restore(states[det.task_id])
        alert_count_at_cp = sum(
            states.get(d.task_id, {}).get("num_alerts", 0)
            for d in self.detectors
        )
        self.alerts = self.alerts[:alert_count_at_cp]

    def resume(self) -> List[FraudAlert]:
        while True:
            txn = self.source.emit_next()
            if txn is None:
                break
            part = self._route(txn)
            det = self.detectors[part]
            wm = self.source.current_watermark
            combined = self.wm_combiners[part].update(0, wm)
            det.advance_watermark(combined)
            alert = det.process(txn)
            if alert:
                self.alerts.append(alert)
        return self.alerts
