"""
Undirected adjacency-list graph for interference / move graphs.
"""


class UndirectedAdjList:
    def __init__(self):
        self._adj = {}
        self._edges = set()

    def add_vertex(self, v):
        if v not in self._adj:
            self._adj[v] = set()

    def add_edge(self, u, v):
        if u == v:
            return
        self.add_vertex(u)
        self.add_vertex(v)
        self._adj[u].add(v)
        self._adj[v].add(u)
        self._edges.add(frozenset((u, v)))

    def has_edge(self, u, v):
        return frozenset((u, v)) in self._edges

    def adjacent(self, u):
        self.add_vertex(u)
        return self._adj[u]

    def vertices(self):
        return self._adj.keys()

    def edges(self):
        return self._edges

    def degree(self, u):
        return len(self._adj.get(u, set()))
