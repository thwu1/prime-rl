
"""
Streaming financial reconciliation engine.

Provides the main entry point for ingesting transaction events and
querying materialized view state. Coordinates the pipeline's progress
tracking, operator processing, and snapshot emission.

Architecture:
    Events flow through: ingestion -> buffering -> epoch drain ->
    operator processing -> snapshot emission.

    The progress tracker manages watermark advancement and event
    buffering. When the watermark advances, buffered events below
    the watermark are drained and processed through the credit and
    debit aggregation operators. A snapshot is then emitted capturing
    the synchronized state of all views.
"""

from pipeline.progress import ProgressTracker
from pipeline.operators import CreditAggregator, DebitAggregator, BalanceJoiner
from pipeline.snapshot import SnapshotEmitter


class IncrementalViewEngine:
    """Main engine class for streaming transaction processing.

    Maintains materialized views of account credits, debits, and
    balances as transactions are ingested from an event stream.

    Usage:
        engine = IncrementalViewEngine(watermark_delay=5)
        for event in stream:
            engine.ingest(event['arrival_time'], event)
        engine.finalize()
        checkpoints = engine.get_checkpoints()
    """

    def __init__(self, watermark_delay):
        """Initialize the engine with the given watermark delay.

        Args:
            watermark_delay: Integer delay for watermark computation.
                Watermark = max(observed event times) - delay.
                Larger delays tolerate more out-of-order data but
                increase latency.
        """
        self.tracker = ProgressTracker(watermark_delay)
        self.credit_op = CreditAggregator()
        self.debit_op = DebitAggregator()
        self.joiner = BalanceJoiner()
        self.emitter = SnapshotEmitter()
        self.rejected_count = 0

    def ingest(self, arrival_time, transaction):
        """Ingest a single transaction event.

        Buffers the event and checks whether the watermark should
        advance. If it does, all events below the new watermark are
        drained from the buffer and processed through the operator
        pipeline, producing a new checkpoint.

        Args:
            arrival_time: Wall-clock arrival time (float)
            transaction: Dict with keys id, from_account, to_account,
                        amount, ts (event time integer)
        """
        # Reject late data at the system edge
        if self.tracker.is_late(transaction):
            self.rejected_count += 1
            return

        self.tracker.buffer_event(transaction)

        # Check if watermark should advance
        new_wm, drained = self.tracker.try_advance()

        if drained:
            # Process drained events through the operator pipeline
            self.credit_op.process(drained)

            # Emit consistent snapshot at the new watermark boundary
            snapshot = self.emitter.create_snapshot(
                new_wm, self.credit_op, self.debit_op, self.joiner
            )
            self.emitter.store(snapshot)

            self.debit_op.process(drained)

    def finalize(self):
        """Signal end of input stream and process remaining buffered events.

        Advances the watermark past the maximum buffered timestamp to
        flush all remaining events through the pipeline.
        """
        if self.tracker.buffer:
            max_ts = max(e['ts'] for e in self.tracker.buffer)
            # Advance watermark to flush remaining buffered events
            new_wm, drained = self.tracker.force_advance(max_ts)
            if drained:
                self.credit_op.process(drained)
                self.debit_op.process(drained)
                snapshot = self.emitter.create_snapshot(
                    new_wm, self.credit_op, self.debit_op, self.joiner
                )
                self.emitter.store(snapshot)

    def get_checkpoints(self):
        """Return all emitted checkpoints in chronological order.

        Each checkpoint is a dict with keys:
            watermark: int - the watermark value at emission time
            credits: dict - account -> total credited amount
            debits: dict - account -> total debited amount
            balance: dict - account -> net balance
            total: int - sum of all balances (should be 0)
        """
        return self.emitter.checkpoints

    def get_rejected_count(self):
        """Return the count of rejected (late) transactions."""
        return self.rejected_count
