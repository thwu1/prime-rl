import threading


class TimestampOracle:
    """Produces strictly increasing timestamps.

    All transactions obtain unique timestamps from this oracle to establish
    a global ordering. Thread-safe.
    """

    def __init__(self):
        self._counter = 0
        self._lock = threading.Lock()

    def get_timestamp(self):
        """Return the next strictly increasing timestamp."""
        with self._lock:
            self._counter += 1
            return self._counter
