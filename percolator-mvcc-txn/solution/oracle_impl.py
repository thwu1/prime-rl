"""Timestamp oracle backed by Redis INCR for cross-process uniqueness."""

import redis


class TimestampOracle:
    """Globally unique, monotonically increasing timestamp generator.

    Uses Redis INCR on a fixed key to guarantee uniqueness across threads
    and across independent OS processes on the same host.
    """

    _COUNTER_KEY = "mvcc:tso:counter"

    def __init__(self, host="localhost", port=6379):
        self._client = redis.Redis(host=host, port=port)

    def get_timestamp(self) -> int:
        return self._client.incr(self._COUNTER_KEY)
