from program import dijkstra


def test_single_node():
    graph = {'A': []}
    assert dijkstra(graph, 'A') == {'A': 0}


def test_two_nodes():
    graph = {'A': [('B', 5)], 'B': []}
    result = dijkstra(graph, 'A')
    assert result == {'A': 0, 'B': 5}


def test_triangle():
    graph = {
        'A': [('B', 1), ('C', 4)],
        'B': [('C', 2)],
        'C': []
    }
    result = dijkstra(graph, 'A')
    assert result == {'A': 0, 'B': 1, 'C': 3}


def test_diamond():
    graph = {
        'S': [('A', 1), ('B', 4)],
        'A': [('B', 2), ('T', 6)],
        'B': [('T', 3)],
        'T': []
    }
    result = dijkstra(graph, 'S')
    assert result == {'S': 0, 'A': 1, 'B': 3, 'T': 6}


def test_disconnected():
    graph = {'A': [('B', 1)], 'B': [], 'C': []}
    result = dijkstra(graph, 'A')
    assert 'C' not in result
    assert result['B'] == 1
