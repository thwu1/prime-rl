
"""Graph library providing directed and undirected adjacency list representations."""

from collections import deque


class Edge:
    def __init__(self, src, tgt):
        self.source = src
        self.target = tgt

    def raw(self):
        return (self.source, self.target)

    def flip(self):
        return Edge(self.target, self.source)

    def __repr__(self):
        return repr(self.raw())

    def __hash__(self):
        return hash(self.raw())

    def __eq__(self, other):
        return self.raw() == other.raw()


class UEdge(Edge):
    """Undirected edge: UEdge(a,b) == UEdge(b,a)."""
    def raw(self):
        return frozenset([self.source, self.target])

    def __hash__(self):
        return hash(self.source) + hash(self.target)

    def __eq__(self, other):
        return (isinstance(other, UEdge)
                and frozenset([self.source, self.target])
                    == frozenset([other.source, other.target]))


class DirectedAdjList:
    def __init__(self, edge_list=None):
        self.out = {}
        self.ins = {}
        self.edge_set = set()
        if edge_list:
            for e in edge_list:
                if isinstance(e, Edge):
                    self.add_edge(e.source, e.target)
                else:
                    self.add_edge(e[0], e[1])

    def edges(self):
        return self.edge_set

    def vertices(self):
        return self.out.keys()

    def num_vertices(self):
        return len(self.out)

    def adjacent(self, u):
        self.add_vertex(u)
        return self.out[u]

    def add_vertex(self, u):
        if u not in self.out:
            self.out[u] = []
            self.ins[u] = []

    def add_edge(self, u, v):
        self.add_vertex(u)
        self.add_vertex(v)
        self.out[u].append(v)
        self.ins[v].append(u)
        edge = Edge(u, v)
        self.edge_set.add(edge)
        return edge

    def has_edge(self, u, v):
        return Edge(u, v) in self.edge_set

    def remove_edge(self, u, v):
        self.out[u].remove(v)
        self.ins[v].remove(u)
        self.edge_set.remove(Edge(u, v))


class UndirectedAdjList(DirectedAdjList):
    """Undirected adjacency list graph."""

    def add_edge(self, u, v):
        self.add_vertex(u)
        self.add_vertex(v)
        self.out[u].append(v)
        self.out[v].append(u)
        edge = UEdge(u, v)
        self.edge_set.add(edge)
        return edge

    def remove_edge(self, u, v):
        self.out[u] = [w for w in self.out[u] if w != v]
        self.out[v] = [w for w in self.out[v] if w != u]
        self.edge_set.discard(UEdge(u, v))

    def has_edge(self, u, v):
        return UEdge(u, v) in self.edge_set

    def out_edges(self, u):
        for v in self.out[u]:
            yield UEdge(u, v)

    def in_edges(self, v):
        for u in self.out[v]:
            yield UEdge(u, v)


def topological_sort(G):
    in_degree = {u: 0 for u in G.vertices()}
    for e in G.edges():
        in_degree[e.target] += 1
    queue = deque()
    for u in G.vertices():
        if in_degree[u] == 0:
            queue.append(u)
    topo = []
    while queue:
        u = queue.pop()
        topo.append(u)
        for v in G.adjacent(u):
            in_degree[v] -= 1
            if in_degree[v] == 0:
                queue.append(v)
    return topo


def transpose(G):
    G_t = DirectedAdjList()
    for v in G.vertices():
        G_t.add_vertex(v)
    for e in G.edges():
        G_t.add_edge(e.target, e.source)
    return G_t
