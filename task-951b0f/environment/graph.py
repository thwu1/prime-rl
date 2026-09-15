"""Simple undirected graph for interference and move graphs.

"""


class UndirectedGraph:
    """Undirected graph with hashable vertex objects."""

    def __init__(self):
        self._adj = {}        # vertex -> set of neighbours

    # -- mutators ----------------------------------------------------------

    def add_vertex(self, v):
        if v not in self._adj:
            self._adj[v] = set()

    def add_edge(self, u, v):
        if u == v:
            return                # no self-loops
        self.add_vertex(u)
        self.add_vertex(v)
        self._adj[u].add(v)
        self._adj[v].add(u)

    def remove_vertex(self, v):
        if v in self._adj:
            for u in self._adj[v]:
                self._adj[u].discard(v)
            del self._adj[v]

    # -- queries -----------------------------------------------------------

    def has_edge(self, u, v):
        return u in self._adj and v in self._adj[u]

    def adjacent(self, v):
        """Return the set of neighbours of *v*."""
        return self._adj.get(v, set())

    def degree(self, v):
        return len(self._adj.get(v, set()))

    def vertices(self):
        return set(self._adj.keys())

    def num_vertices(self):
        return len(self._adj)

    def num_edges(self):
        return sum(len(adj) for adj in self._adj.values()) // 2

    def copy(self):
        g = UndirectedGraph()
        for v in self._adj:
            g._adj[v] = set(self._adj[v])
        return g

    def __contains__(self, v):
        return v in self._adj

    def __repr__(self):
        return f"UndirectedGraph(V={self.num_vertices()}, E={self.num_edges()})"
