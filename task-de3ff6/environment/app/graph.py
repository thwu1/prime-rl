
"""
Undirected and directed adjacency list graph libraries.
Based on Siek's Essentials of Compilation support code.
"""


class UndirectedAdjList:
    """Undirected graph using adjacency sets (no duplicate edges)."""

    def __init__(self):
        self.adj = {}
        self.edge_set = set()

    def add_vertex(self, v):
        if v not in self.adj:
            self.adj[v] = set()

    def add_edge(self, u, v):
        self.add_vertex(u)
        self.add_vertex(v)
        if u != v:
            self.adj[u].add(v)
            self.adj[v].add(u)
            self.edge_set.add(frozenset([u, v]))

    def has_edge(self, u, v):
        return frozenset([u, v]) in self.edge_set

    def remove_edge(self, u, v):
        self.adj[u].discard(v)
        self.adj[v].discard(u)
        self.edge_set.discard(frozenset([u, v]))

    def adjacent(self, u):
        self.add_vertex(u)
        return self.adj[u]

    def vertices(self):
        return self.adj.keys()

    def edges(self):
        return self.edge_set

    def degree(self, u):
        return len(self.adjacent(u))

    def num_vertices(self):
        return len(self.adj)

    def __repr__(self):
        edges = [tuple(e) for e in self.edge_set]
        return f"UndirectedAdjList(vertices={list(self.adj.keys())}, edges={edges})"


class DirectedAdjList:
    """Directed graph using adjacency lists."""

    def __init__(self):
        self.out = {}
        self.ins = {}

    def add_vertex(self, v):
        if v not in self.out:
            self.out[v] = []
            self.ins[v] = []

    def add_edge(self, u, v):
        self.add_vertex(u)
        self.add_vertex(v)
        self.out[u].append(v)
        self.ins[v].append(u)

    def successors(self, u):
        self.add_vertex(u)
        return self.out[u]

    def predecessors(self, v):
        self.add_vertex(v)
        return self.ins[v]

    def vertices(self):
        return self.out.keys()
