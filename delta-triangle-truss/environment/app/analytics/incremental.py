"""
Incremental triangle counting using delta queries.

When an edge (u, v) is inserted or deleted, the change in the total
triangle count equals |N(u) ∩ N(v)| — the number of common neighbors.
Each common neighbor w defines a triangle {u, v, w} that is created
or destroyed by the operation.

Per-node triangle participation is tracked alongside the total count.
"""
from collections import defaultdict


class IncrementalTriangleCounting:
    """Maintains triangle counts incrementally as edges are inserted/removed."""

    def __init__(self, graph):
        self.graph = graph
        self.total_tri = 0
        self.node_tri = defaultdict(int)

    def bootstrap(self, edges):
        """Initialize counts by processing an initial edge list one at a time.

        Edges are added sequentially; for each new edge (u, v), the delta
        is the number of common neighbors at the time of insertion.
        """
        for u, v in edges:
            common = self.graph.common_neighbors(u, v)
            delta = len(common)
            self.total_tri += delta
            self.node_tri[u] += delta
            self.node_tri[v] += delta
            for w in common:
                self.node_tri[w] += 1
            self.graph.add_edge(u, v)

    def apply_operation(self, op, u, v):
        """Apply a single edge operation: '+' for insertion, '-' for deletion.

        The delta (common neighbor count) is computed before modifying the
        graph, so that the adjacency reflects the state prior to the change.
        """
        common = self.graph.common_neighbors(u, v)
        delta = len(common)

        if op == '+':
            self.total_tri += delta
            self.node_tri[u] += delta
            self.node_tri[v] += delta
            for w in common:
                self.node_tri[w] += 1
            self.graph.add_edge(u, v)

        elif op == '-':
            self.total_tri -= delta
            self.node_tri[u] -= delta
            self.node_tri[v] -= delta
            self.graph.remove_edge(u, v)

    def get_total_triangles(self):
        """Return the current total triangle count."""
        return self.total_tri

    def get_node_triangles(self):
        """Return dict mapping node_id to positive triangle participation count."""
        return {n: c for n, c in self.node_tri.items() if c > 0}
