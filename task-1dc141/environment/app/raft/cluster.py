"""
Cluster management for the Raft consensus system.

Provides a deterministic, tick-based simulation environment for
running and testing a Raft cluster. No threads or async — the
cluster drives the simulation by ticking all nodes in round-robin
order.

"""

import random
from .node import RaftNode
from .transport import Transport
from .protocol import NodeState


class Cluster:
    """Manages a cluster of Raft nodes in a deterministic simulation."""

    def __init__(self, n_nodes, seed=42):
        self.transport = Transport()
        self.n_nodes = n_nodes
        self.rng = random.Random(seed)
        self.nodes = {}
        self._dead_nodes = set()

        peer_ids = list(range(n_nodes))
        for i in range(n_nodes):
            node = RaftNode(
                node_id=i,
                peers=[p for p in peer_ids if p != i],
                transport=self.transport,
                seed=self.rng.randint(0, 2**32),
            )
            self.nodes[i] = node

    def tick(self, n=1):
        """Advance the simulation by n ticks.

        Each tick, every live node processes its pending messages
        and checks its timeouts.
        """
        for _ in range(n):
            for nid in range(self.n_nodes):
                if nid not in self._dead_nodes:
                    self.nodes[nid].tick()

    def get_leader(self):
        """Return the node_id of the current leader, or None.

        Returns None if there are zero or multiple leaders (ambiguous).
        """
        leaders = []
        for nid in range(self.n_nodes):
            if nid not in self._dead_nodes and self.nodes[nid].state == NodeState.LEADER:
                leaders.append(nid)
        if len(leaders) == 1:
            return leaders[0]
        return None

    def get_leaders(self):
        """Return a list of all live nodes that believe they are leader."""
        return [
            nid
            for nid in range(self.n_nodes)
            if nid not in self._dead_nodes and self.nodes[nid].state == NodeState.LEADER
        ]

    def wait_for_leader(self, max_ticks=2000):
        """Tick until exactly one leader exists, or give up.

        Returns the leader's node_id, or None if no single leader
        emerged within max_ticks.
        """
        for _ in range(max_ticks):
            self.tick()
            leader = self.get_leader()
            if leader is not None:
                return leader
        return None

    def submit(self, command, leader_id=None):
        """Submit a command to the leader for replication.

        Returns True if the command was accepted, False otherwise.
        """
        if leader_id is None:
            leader_id = self.get_leader()
        if leader_id is None:
            return False
        return self.nodes[leader_id].submit(command)

    def kill_node(self, node_id):
        """Simulate a node crash. The node stops ticking and its
        inbox is cleared."""
        self._dead_nodes.add(node_id)
        self.transport.clear(node_id)

    def restart_node(self, node_id):
        """Restart a previously killed node.

        Persistent state (currentTerm, votedFor, log) is preserved.
        Volatile state is reset as if the node just booted.
        """
        if node_id in self._dead_nodes:
            self._dead_nodes.discard(node_id)
            self.transport.clear(node_id)
            self.nodes[node_id].restart()

    def partition(self, group_a, group_b):
        """Create a network partition between two groups of nodes."""
        self.transport.partition(group_a, group_b)

    def heal(self):
        """Remove all network partitions."""
        self.transport.heal()

    def get_committed_value(self, node_id, key):
        """Read a committed value from a node's state machine."""
        return self.nodes[node_id].state_machine.get(key)
