from .errors import RequestDroppedError, ResponseDroppedError


class Client:
    """Transaction client with snapshot isolation."""

    def __init__(self, tso, storage):
        self._tso = tso
        self._storage = storage
        self._start_ts = 0
        self._write_buffer = {}

    def begin(self):
        """Start a new transaction."""
        raise NotImplementedError

    def get(self, key):
        """Read key in the current snapshot. Returns bytes."""
        raise NotImplementedError

    def set(self, key, value):
        """Buffer a write for commit time."""
        raise NotImplementedError

    def commit(self):
        """Commit the transaction. Returns True/False.
        May raise ResponseDroppedError on ambiguous primary outcome."""
        raise NotImplementedError
