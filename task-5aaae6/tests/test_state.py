"""Tests for the graphdb PyO3 extension module."""


import pytest
import threading
import time


class TestImport:
    def test_import_module(self):
        import graphdb
        assert hasattr(graphdb, "Graph")
        assert hasattr(graphdb, "Node")
        assert hasattr(graphdb, "Edge")


class TestNode:
    def test_create(self):
        from graphdb import Node
        n = Node("alpha")
        assert n.id == "alpha"

    def test_properties(self):
        from graphdb import Node
        n = Node("n1")
        n.set_property("color", "red")
        n.set_property("size", "large")
        assert n.get_property("color") == "red"
        assert n.get_property("size") == "large"
        assert n.property_count == 2

    def test_missing_property(self):
        from graphdb import Node
        n = Node("n1")
        with pytest.raises(KeyError):
            n.get_property("nonexistent")

    def test_equality(self):
        from graphdb import Node
        a1 = Node("a")
        a2 = Node("a")
        b = Node("b")
        assert a1 == a2
        assert a1 != b
        assert not (a1 == b)
        assert not (a1 != a2)

    def test_repr_str(self):
        from graphdb import Node
        n = Node("x")
        assert "x" in repr(n)
        assert str(n) == "x"

    def test_hashable_in_set(self):
        from graphdb import Node
        n1 = Node("a")
        n2 = Node("b")
        n3 = Node("a")
        s = {n1, n2, n3}
        assert len(s) == 2

    def test_hashable_as_dict_key(self):
        from graphdb import Node
        n = Node("key_node")
        d = {n: 42}
        assert d[n] == 42

    def test_equal_nodes_same_hash(self):
        from graphdb import Node
        n1 = Node("same")
        n2 = Node("same")
        assert n1 == n2
        assert hash(n1) == hash(n2)


class TestGraphBasic:
    def test_create(self):
        from graphdb import Graph
        g = Graph()
        assert g.node_count() == 0
        assert g.edge_count() == 0

    def test_add_nodes(self):
        from graphdb import Graph
        g = Graph()
        g.add_node("a")
        g.add_node("b")
        g.add_node("c")
        assert g.node_count() == 3
        assert g.has_node("a")
        assert g.has_node("b")
        assert not g.has_node("z")

    def test_duplicate_node(self):
        from graphdb import Graph
        g = Graph()
        g.add_node("a")
        with pytest.raises(ValueError):
            g.add_node("a")

    def test_get_node(self):
        from graphdb import Graph
        g = Graph()
        g.add_node("x")
        n = g.get_node("x")
        assert n.id == "x"

    def test_get_missing_node(self):
        from graphdb import Graph
        g = Graph()
        with pytest.raises(KeyError):
            g.get_node("missing")

    def test_node_ids(self):
        from graphdb import Graph
        g = Graph()
        g.add_node("a")
        g.add_node("b")
        ids = sorted(g.node_ids())
        assert ids == ["a", "b"]

    def test_len_contains(self):
        from graphdb import Graph
        g = Graph()
        g.add_node("x")
        g.add_node("y")
        assert len(g) == 2
        assert "x" in g
        assert "z" not in g

    def test_repr(self):
        from graphdb import Graph
        g = Graph()
        g.add_node("a")
        r = repr(g)
        assert "nodes=1" in r


class TestEdges:
    def test_add_directed_edge(self):
        from graphdb import Graph
        g = Graph()
        g.add_node("a")
        g.add_node("b")
        g.add_edge("a", "b", {"weight": 1.5, "directed": True, "label": "road"})
        assert g.edge_count() == 1
        neighbors = g.get_neighbors("a")
        assert len(neighbors) == 1
        assert neighbors[0] == ("b", 1.5)
        assert len(g.get_neighbors("b")) == 0

    def test_add_undirected_edge(self):
        from graphdb import Graph
        g = Graph()
        g.add_node("a")
        g.add_node("b")
        g.add_edge("a", "b", {"weight": 2.0, "directed": False, "label": None})
        assert g.edge_count() == 1
        assert len(g.get_neighbors("a")) == 1
        assert len(g.get_neighbors("b")) == 1

    def test_edge_missing_node(self):
        from graphdb import Graph
        g = Graph()
        g.add_node("a")
        with pytest.raises(KeyError):
            g.add_edge("a", "b", {"weight": 1.0, "directed": True, "label": None})

    def test_get_edges(self):
        from graphdb import Graph
        g = Graph()
        g.add_node("x")
        g.add_node("y")
        g.add_edge("x", "y", {"weight": 3.0, "directed": True, "label": "e1"})
        edges = g.get_edges()
        assert len(edges) == 1
        assert edges[0].source == "x"
        assert edges[0].target == "y"
        assert edges[0].weight == 3.0
        assert edges[0].label == "e1"

    def test_multiple_edges(self):
        from graphdb import Graph
        g = Graph()
        for n in ["a", "b", "c"]:
            g.add_node(n)
        g.add_edge("a", "b", {"weight": 1.0, "directed": True, "label": None})
        g.add_edge("b", "c", {"weight": 2.0, "directed": True, "label": None})
        g.add_edge("a", "c", {"weight": 5.0, "directed": True, "label": None})
        assert g.edge_count() == 3


class TestToDict:
    def test_basic(self):
        from graphdb import Graph
        g = Graph()
        g.add_node("p")
        g.add_node("q")
        g.add_edge("p", "q", {"weight": 7.0, "directed": True, "label": None})
        d = g.to_dict()
        assert "nodes" in d
        assert "edges" in d
        assert sorted(d["nodes"]) == ["p", "q"]
        assert len(d["edges"]) == 1
        edge = d["edges"][0]
        assert edge[0] == "p"
        assert edge[1] == "q"
        assert edge[2] == 7.0

    def test_empty_graph(self):
        from graphdb import Graph
        g = Graph()
        d = g.to_dict()
        assert d["nodes"] == []
        assert d["edges"] == []


class TestShortestPath:
    def test_simple_path(self):
        from graphdb import Graph
        g = Graph()
        for n in ["a", "b", "c", "d"]:
            g.add_node(n)
        g.add_edge("a", "b", {"weight": 1.0, "directed": True, "label": None})
        g.add_edge("b", "c", {"weight": 2.0, "directed": True, "label": None})
        g.add_edge("a", "c", {"weight": 10.0, "directed": True, "label": None})
        g.add_edge("c", "d", {"weight": 1.0, "directed": True, "label": None})

        result = g.shortest_path("a", "d")
        assert result is not None
        path, cost = result
        assert path == ["a", "b", "c", "d"]
        assert abs(cost - 4.0) < 1e-9

    def test_no_path(self):
        from graphdb import Graph
        g = Graph()
        g.add_node("a")
        g.add_node("b")
        result = g.shortest_path("a", "b")
        assert result is None

    def test_direct_path(self):
        from graphdb import Graph
        g = Graph()
        g.add_node("s")
        g.add_node("t")
        g.add_edge("s", "t", {"weight": 5.0, "directed": True, "label": None})
        result = g.shortest_path("s", "t")
        assert result is not None
        path, cost = result
        assert path == ["s", "t"]
        assert abs(cost - 5.0) < 1e-9

    def test_missing_source(self):
        from graphdb import Graph
        g = Graph()
        g.add_node("a")
        with pytest.raises(KeyError):
            g.shortest_path("missing", "a")


class TestPageRank:
    def test_cycle(self):
        from graphdb import Graph
        g = Graph()
        for n in ["a", "b", "c"]:
            g.add_node(n)
        g.add_edge("a", "b", {"weight": 1.0, "directed": True, "label": None})
        g.add_edge("b", "c", {"weight": 1.0, "directed": True, "label": None})
        g.add_edge("c", "a", {"weight": 1.0, "directed": True, "label": None})

        ranks = g.pagerank(0.85, 100)
        assert len(ranks) == 3
        for v in ranks.values():
            assert abs(v - 1.0 / 3.0) < 0.01

    def test_star(self):
        from graphdb import Graph
        g = Graph()
        g.add_node("center")
        for i in range(4):
            name = f"leaf_{i}"
            g.add_node(name)
            g.add_edge(name, "center", {"weight": 1.0, "directed": True, "label": None})

        ranks = g.pagerank(0.85, 100)
        assert ranks["center"] > ranks["leaf_0"]

    def test_ranks_sum_to_one(self):
        """Ranks must sum to 1.0 even when the graph contains nodes with no outgoing edges."""
        from graphdb import Graph
        g = Graph()
        for n in ["a", "b", "c", "sink"]:
            g.add_node(n)
        g.add_edge("a", "b", {"weight": 1.0, "directed": True, "label": None})
        g.add_edge("b", "c", {"weight": 1.0, "directed": True, "label": None})
        ranks = g.pagerank(0.85, 100)
        total = sum(ranks.values())
        assert abs(total - 1.0) < 0.01, f"Ranks sum to {total}, expected ~1.0"

    def test_sink_node_accumulates_rank(self):
        """A sink node reachable from other nodes must accumulate significant rank."""
        from graphdb import Graph
        g = Graph()
        g.add_node("source")
        g.add_node("sink")
        g.add_edge("source", "sink", {"weight": 1.0, "directed": True, "label": None})
        ranks = g.pagerank(0.85, 200)
        total = sum(ranks.values())
        assert abs(total - 1.0) < 0.01, f"Ranks sum to {total}, expected ~1.0"
        assert ranks["sink"] > 0.3, f"Sink rank {ranks['sink']} too low"


class TestAdjacencyMatrix:
    def test_basic(self):
        from graphdb import Graph
        g = Graph()
        g.add_node("b")
        g.add_node("a")
        g.add_node("c")
        g.add_edge("a", "b", {"weight": 2.0, "directed": True, "label": None})
        g.add_edge("b", "c", {"weight": 3.0, "directed": True, "label": None})
        ids, matrix = g.to_adjacency_matrix()
        assert ids == ["a", "b", "c"]
        assert matrix[0][1] == 2.0  # a->b
        assert matrix[1][2] == 3.0  # b->c
        assert matrix[0][2] == 0.0  # no a->c
        assert matrix[2][0] == 0.0  # no c->a

    def test_undirected(self):
        from graphdb import Graph
        g = Graph()
        g.add_node("x")
        g.add_node("y")
        g.add_edge("x", "y", {"weight": 5.0, "directed": False, "label": None})
        ids, matrix = g.to_adjacency_matrix()
        assert ids == ["x", "y"]
        assert matrix[0][1] == 5.0
        assert matrix[1][0] == 5.0

    def test_empty(self):
        from graphdb import Graph
        g = Graph()
        ids, matrix = g.to_adjacency_matrix()
        assert ids == []
        assert matrix == []

    def test_isolated_nodes(self):
        from graphdb import Graph
        g = Graph()
        g.add_node("a")
        g.add_node("b")
        ids, matrix = g.to_adjacency_matrix()
        assert ids == ["a", "b"]
        assert matrix == [[0.0, 0.0], [0.0, 0.0]]

    def test_multiple_edges_sum(self):
        """Multiple edges between the same pair should have weights summed."""
        from graphdb import Graph
        g = Graph()
        g.add_node("a")
        g.add_node("b")
        g.add_edge("a", "b", {"weight": 1.0, "directed": True, "label": None})
        g.add_edge("a", "b", {"weight": 2.0, "directed": True, "label": "extra"})
        ids, matrix = g.to_adjacency_matrix()
        assert matrix[0][1] == 3.0


class TestConnectedComponents:
    def test_single_component(self):
        from graphdb import Graph
        g = Graph()
        for n in ["a", "b", "c"]:
            g.add_node(n)
        g.add_edge("a", "b", {"weight": 1.0, "directed": True, "label": None})
        g.add_edge("b", "c", {"weight": 1.0, "directed": True, "label": None})
        comps = g.connected_components()
        assert len(comps) == 1
        assert comps[0] == ["a", "b", "c"]

    def test_multiple_components(self):
        from graphdb import Graph
        g = Graph()
        for n in ["a", "b", "c", "x", "y"]:
            g.add_node(n)
        g.add_edge("a", "b", {"weight": 1.0, "directed": True, "label": None})
        g.add_edge("b", "c", {"weight": 1.0, "directed": True, "label": None})
        g.add_edge("x", "y", {"weight": 1.0, "directed": True, "label": None})
        comps = g.connected_components()
        assert len(comps) == 2
        assert comps[0] == ["a", "b", "c"]
        assert comps[1] == ["x", "y"]

    def test_isolated_nodes(self):
        from graphdb import Graph
        g = Graph()
        g.add_node("z")
        g.add_node("a")
        comps = g.connected_components()
        assert len(comps) == 2
        assert comps[0] == ["a"]
        assert comps[1] == ["z"]

    def test_directed_treated_as_undirected(self):
        """Directed edges still create undirected connectivity for components."""
        from graphdb import Graph
        g = Graph()
        g.add_node("a")
        g.add_node("b")
        g.add_edge("a", "b", {"weight": 1.0, "directed": True, "label": None})
        comps = g.connected_components()
        assert len(comps) == 1
        assert comps[0] == ["a", "b"]

    def test_empty_graph(self):
        from graphdb import Graph
        g = Graph()
        comps = g.connected_components()
        assert comps == []

    def test_complex_topology(self):
        """Multiple components with varying sizes and mixed edge types."""
        from graphdb import Graph
        g = Graph()
        for n in ["a", "b", "c", "d", "e", "f", "g"]:
            g.add_node(n)
        g.add_edge("a", "b", {"weight": 1.0, "directed": True, "label": None})
        g.add_edge("c", "b", {"weight": 1.0, "directed": True, "label": None})
        g.add_edge("d", "e", {"weight": 1.0, "directed": False, "label": None})
        # f and g are isolated
        comps = g.connected_components()
        assert len(comps) == 4
        assert comps[0] == ["a", "b", "c"]
        assert comps[1] == ["d", "e"]
        assert comps[2] == ["f"]
        assert comps[3] == ["g"]


class TestConcurrency:
    def test_concurrent_add_node(self):
        from graphdb import Graph
        g = Graph()
        errors = []

        def add_batch(prefix, count):
            try:
                for i in range(count):
                    try:
                        g.add_node(f"{prefix}_{i}")
                    except ValueError:
                        pass
            except RuntimeError as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=add_batch, args=(f"t{t}", 20))
            for t in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Runtime borrow errors: {errors}"
        assert g.node_count() > 0

    def test_concurrent_add_node_with_props(self):
        from graphdb import Graph
        g = Graph()
        errors = []

        def writer(prefix):
            try:
                for i in range(5):
                    try:
                        g.add_node_with_props(f"{prefix}_{i}", {"k": f"v{i}"})
                    except ValueError:
                        pass
            except RuntimeError as e:
                errors.append(str(e))

        def reader():
            try:
                for _ in range(50):
                    g.node_count()
                    time.sleep(0.005)
            except RuntimeError as e:
                errors.append(str(e))

        t_write = threading.Thread(target=writer, args=("w",))
        t_read = threading.Thread(target=reader)

        t_write.start()
        t_read.start()
        t_write.join()
        t_read.join()

        assert len(errors) == 0, f"Borrow errors during concurrent access: {errors}"
