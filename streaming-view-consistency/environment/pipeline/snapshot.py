
"""
Checkpoint and snapshot management for pipeline state.

Creates consistent snapshots of all materialized views at watermark
boundaries. Each snapshot captures credits, debits, balance, and total
at a specific point in the input stream.
"""


class SnapshotEmitter:
    """Creates and stores pipeline state snapshots at epoch boundaries."""

    def __init__(self):
        self.checkpoints = []

    def create_snapshot(self, watermark, credit_op, debit_op, joiner):
        """Create a snapshot of current pipeline state.

        Captures the state of all operators and computes derived views.
        For the snapshot to be consistent, all operators must reflect
        the same set of processed input events.

        Args:
            watermark: The watermark value for this snapshot
            credit_op: CreditAggregator instance
            debit_op: DebitAggregator instance
            joiner: BalanceJoiner instance

        Returns:
            dict with keys: watermark, credits, debits, balance, total
        """
        credits = credit_op.get_state()
        debits = debit_op.get_state()
        balance = joiner.compute(credits, debits)
        total = sum(balance.values())

        return {
            'watermark': watermark,
            'credits': credits,
            'debits': debits,
            'balance': balance,
            'total': total,
        }

    def store(self, snapshot):
        """Store a snapshot for later retrieval."""
        self.checkpoints.append(snapshot)

    @property
    def count(self):
        """Number of stored snapshots."""
        return len(self.checkpoints)
