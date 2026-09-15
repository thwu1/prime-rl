"""Graph utilities for register allocation (undirected adjacency list)."""


class UndirectedAdjList:
    """Simple undirected graph using adjacency sets."""

    def __init__(self):
        self.adj = {}

    def add_vertex(self, v):
        if v not in self.adj:
            self.adj[v] = set()

    def add_edge(self, u, v):
        if u == v:
            return
        self.add_vertex(u)
        self.add_vertex(v)
        self.adj[u].add(v)
        self.adj[v].add(u)

    def has_edge(self, u, v):
        return u in self.adj and v in self.adj[u]

    def adjacent(self, u):
        self.add_vertex(u)
        return self.adj[u]

    def vertices(self):
        return set(self.adj.keys())

    def degree(self, u):
        self.add_vertex(u)
        return len(self.adj[u])
