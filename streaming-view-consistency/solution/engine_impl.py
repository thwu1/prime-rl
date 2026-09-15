
"""
Internally-consistent streaming view maintenance engine.

Uses watermark-based progress tracking to ensure every emitted checkpoint
reflects the correct state for exactly the set of finalized transactions.

Key design choices:
- Buffer incoming transactions by event time (ts)
- Watermark = max(observed event times) - watermark_delay
- When watermark advances, atomically process ALL buffered events with ts < watermark
- Compute credits, debits, balance, total from the same processed set
- Reject late arrivals (ts < current_watermark) at the system edge
- Emit checkpoint only when new data is actually processed
"""


class IncrementalViewEngine:
    """Streaming engine that maintains credits/debits/balance/total views
    with internal consistency guarantees."""

    def __init__(self, watermark_delay):
        self.watermark_delay = watermark_delay
        self.max_event_time = None
        self.current_watermark = None
        self.buffer = {}          # event_time -> [transaction, ...]
        self.checkpoints = []
        self.rejected_count = 0
        # Accumulated view state
        self.credits = {}         # account -> total credited amount
        self.debits = {}          # account -> total debited amount

    def ingest(self, arrival_time, transaction):
        """Ingest a single transaction. Reject if late (ts < watermark)."""
        event_time = transaction['ts']

        # Reject late data at the system edge
        if self.current_watermark is not None and event_time < self.current_watermark:
            self.rejected_count += 1
            return

        # Buffer by event time
        if event_time not in self.buffer:
            self.buffer[event_time] = []
        self.buffer[event_time].append(transaction)

        # Advance watermark if we see a new max event time
        if self.max_event_time is None or event_time > self.max_event_time:
            self.max_event_time = event_time
            new_watermark = self.max_event_time - self.watermark_delay
            if self.current_watermark is None or new_watermark > self.current_watermark:
                self._advance_watermark(new_watermark)

    def _advance_watermark(self, new_watermark):
        """Process all buffered events with ts < new_watermark and emit checkpoint."""
        # Find all buffered timestamps that are now finalized
        times_to_process = sorted(t for t in self.buffer if t < new_watermark)

        if times_to_process:
            # Atomically process all finalized events
            for t in times_to_process:
                for txn in self.buffer[t]:
                    to_acc = txn['to_account']
                    from_acc = txn['from_account']
                    amount = txn['amount']
                    self.credits[to_acc] = self.credits.get(to_acc, 0) + amount
                    self.debits[from_acc] = self.debits.get(from_acc, 0) + amount
                del self.buffer[t]

            # Compute derived views from synchronized state
            balance = {}
            all_accounts = set(self.credits.keys()) | set(self.debits.keys())
            for acc in all_accounts:
                balance[acc] = self.credits.get(acc, 0) - self.debits.get(acc, 0)

            self.checkpoints.append({
                'watermark': new_watermark,
                'credits': dict(self.credits),
                'debits': dict(self.debits),
                'balance': dict(balance),
                'total': sum(balance.values()),
            })

        self.current_watermark = new_watermark

    def get_checkpoints(self):
        """Return all emitted checkpoints in chronological order."""
        return self.checkpoints

    def finalize(self):
        """Process all remaining buffered data."""
        if self.buffer:
            max_buffered = max(self.buffer.keys())
            # Advance watermark past the last buffered time to flush everything
            self._advance_watermark(max_buffered + 1)

    def get_rejected_count(self):
        """Return count of rejected (late) transactions."""
        return self.rejected_count
