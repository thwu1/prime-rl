"""Timestamp oracle — globally unique, monotonically increasing timestamps."""


class TimestampOracle:
    """Generates strictly monotonically increasing timestamps that are unique
    across threads and across independent OS processes on the same host."""

    def __init__(self):
        raise NotImplementedError

    def get_timestamp(self) -> int:
        """Return the next unique timestamp (positive integer).

        Must be strictly monotonically increasing within a single caller
        and globally unique even when called concurrently from multiple
        threads or separate OS processes."""
        raise NotImplementedError
