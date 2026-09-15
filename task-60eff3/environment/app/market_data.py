"""Market data feed generator.

See SPEC.md for the required output format and semantics.
"""


class MarketDataFeed:
    """Generates trade ticks and BBO updates from order book events."""

    def __init__(self):
        self.entries = []

    def record_event(self, book, trades, aggressor_side, timestamp):
        """Record market data after processing a new order event.

        Must append trade ticks and a BBO update to self.entries.
        See SPEC.md for the exact format.
        """
        raise NotImplementedError("Market data feed not yet implemented")

    def record_cancel(self, book, timestamp):
        """Record market data after processing a cancel event.

        Must append a BBO update to self.entries.
        See SPEC.md for the exact format.
        """
        raise NotImplementedError("Market data feed not yet implemented")
