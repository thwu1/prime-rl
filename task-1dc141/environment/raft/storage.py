"""
State machine for the Raft consensus system.

A simple key-value store that serves as the replicated state machine.
Commands are applied in log order after commitment.

"""


class StateMachine:
    """A simple key-value store state machine."""

    def __init__(self):
        self._data = {}

    def apply(self, command):
        """Apply a command to the state machine. Returns the result."""
        if command is None:
            return None
        op = command.get("op")
        if op == "set":
            self._data[command["key"]] = command["value"]
            return command["value"]
        elif op == "get":
            return self._data.get(command["key"])
        elif op == "delete":
            return self._data.pop(command["key"], None)
        elif op == "noop":
            return None
        return None

    def get(self, key):
        """Read a value directly from the state machine."""
        return self._data.get(key)

    def snapshot(self):
        """Return a copy of the current state."""
        return dict(self._data)

    def restore(self, data):
        """Restore state from a snapshot."""
        self._data = dict(data)
