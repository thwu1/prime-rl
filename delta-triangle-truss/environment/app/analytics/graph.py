"""
Dynamic undirected graph data structure with adjacency set representation.

Supports incremental edge insertion and deletion while maintaining
adjacency sets for efficient neighbor lookups and common-neighbor queries.
"""
from collections import defaultdict


class Graph:
    """Dynamic undirected graph backed by adjacency sets and an edge set."""

    def __init__(self):
        self.adj = defaultdict(set)
        self.edge_set = set()

    def add_edge(self, u, v):
        """Add an undirected edge between u and v."""
        u, v = min(u, v), max(u, v)
        if (u, v) not in self.edge_set:
            self.adj[u].add(v)
            self.adj[v].add(u)
            self.edge_set.add((u, v))

    def remove_edge(self, u, v):
        """Remove an undirected edge between u and v."""
        u, v = min(u, v), max(u, v)
        if (u, v) in self.edge_set:
            self.adj[u].discard(v)
            self.edge_set.discard((u, v))

    def has_edge(self, u, v):
        """Check whether edge (u, v) exists."""
        u, v = min(u, v), max(u, v)
        return (u, v) in self.edge_set

    def common_neighbors(self, u, v):
        """Return the set of nodes adjacent to both u and v."""
        return self.adj[u] & self.adj[v]

    def neighbors(self, u):
        """Return the neighbor set of node u."""
        return self.adj[u]

    def get_edges(self):
        """Return sorted list of all edges as (u, v) tuples with u < v."""
        return sorted(self.edge_set)

    def num_edges(self):
        """Return the number of edges in the graph."""
        return len(self.edge_set)
