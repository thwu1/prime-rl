import heapq


def dijkstra(graph, start):
    """
    Compute shortest distances from start node using Dijkstra's algorithm.
    graph: dict mapping node -> list of (neighbor, weight) tuples.
    Returns: dict mapping each reachable node -> shortest distance.
    """
    dist = {start: 0}
    heap = [(0, start)]
    visited = set()

    while heap:
        d, u = heapq.heappop(heap)
        if u in visited:
            continue
        visited.add(u)
        for v, w in graph.get(u, []):
            new_dist = d + w
            if v not in dist or new_dist < dist[v]:
                dist[v] = new_dist
                heapq.heappush(heap, (new_dist, u))

    return dist
