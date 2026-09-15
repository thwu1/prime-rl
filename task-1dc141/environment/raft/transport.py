"""
Transport layer for the Raft consensus system.

Provides in-process message passing between Raft nodes.
Supports network partition simulation for testing.

"""

from collections import defaultdict, deque


class Transport:
    """Simulated network transport for in-process Raft nodes."""

    def __init__(self):
        self._inboxes = defaultdict(deque)
        self._partitions = set()  # set of frozenset({a, b}) pairs
        self._dropped_count = 0

    def send(self, from_id, to_id, message):
        """Send a message from one node to another.

        Messages between partitioned nodes are silently dropped.
        """
        pair = frozenset({from_id, to_id})
        if pair in self._partitions:
            self._dropped_count += 1
            return
        self._inboxes[to_id].append((from_id, message))

    def receive(self, node_id):
        """Receive the next message for a node (non-blocking).

        Returns (sender_id, message) or None if the inbox is empty.
        """
        if self._inboxes[node_id]:
            return self._inboxes[node_id].popleft()
        return None

    def partition(self, group_a, group_b):
        """Create a network partition between two groups of nodes.

        All messages between any node in group_a and any node in group_b
        will be dropped.
        """
        for a in group_a:
            for b in group_b:
                self._partitions.add(frozenset({a, b}))

    def heal(self):
        """Remove all network partitions."""
        self._partitions.clear()

    def clear(self, node_id):
        """Clear all pending messages for a node."""
        self._inboxes[node_id].clear()

    @property
    def dropped_count(self):
        """Total number of messages dropped due to partitions."""
        return self._dropped_count
