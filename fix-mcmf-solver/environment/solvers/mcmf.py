"""Min-Cost Max-Flow solver using SPFA (Shortest Path Faster Algorithm).

Implements the successive shortest paths algorithm for finding minimum-cost
maximum flow in a directed network. Uses SPFA (a queue-based Bellman-Ford
variant) to find shortest augmenting paths in the residual graph.

Usage:
    solver = MinCostMaxFlow(n)       # n = number of nodes
    solver.add_edge(u, v, cap, cost) # add directed edge
    flow, cost = solver.solve(s, t)  # compute min-cost max-flow
"""

from collections import deque


class MinCostMaxFlow:
    """Solves the minimum-cost maximum-flow problem on a directed graph.

    Edges are stored in adjacency lists. Each edge is represented as:
        [to, residual_capacity, cost, reverse_edge_index]
    where reverse_edge_index is the index of the corresponding reverse edge
    in the destination node's adjacency list.
    """

    def __init__(self, n):
        """Initialize solver for a graph with n nodes (0-indexed)."""
        self.n = n
        self.graph = [[] for _ in range(n)]

    def add_edge(self, frm, to, cap, cost):
        """Add a directed edge from node `frm` to node `to`.

        Args:
            frm: Source node index.
            to: Destination node index.
            cap: Edge capacity (non-negative integer).
            cost: Cost per unit of flow on this edge.
        """
        # Forward edge: full capacity, given cost
        self.graph[frm].append([to, cap, cost, len(self.graph[to])])
        # Reverse edge: zero initial capacity, reverse cost
        self.graph[to].append([frm, 0, cost, len(self.graph[frm]) - 1])

    def solve(self, s, t):
        """Compute minimum-cost maximum-flow from source s to sink t.

        Returns:
            Tuple (max_flow, min_cost) where max_flow is the maximum flow
            value and min_cost is the minimum total cost to achieve it.
        """
        total_flow = 0
        total_cost = 0
        INF = float('inf')

        while True:
            # SPFA: find shortest (minimum cost) augmenting path from s to t
            dist = [INF] * self.n
            in_queue = [False] * self.n
            prev_node = [-1] * self.n
            prev_edge = [-1] * self.n

            dist[s] = 0
            queue = deque([s])
            in_queue[s] = True

            while queue:
                v = queue.popleft()
                in_queue[v] = False
                for i, (to, cap, c, _rev) in enumerate(self.graph[v]):
                    if cap > 0 and dist[v] + c < dist[to]:
                        dist[to] = dist[v] + c
                        prev_node[to] = v
                        prev_edge[to] = i
                        if not in_queue[to]:
                            queue.append(to)
                            in_queue[to] = True

            if dist[t] == INF:
                break

            # Trace back the shortest path to find the bottleneck capacity
            bottleneck = INF
            v = t
            while v != s:
                bottleneck = min(bottleneck, self.graph[v][prev_edge[v]][1])
                v = prev_node[v]

            # Augment flow along the shortest path
            v = t
            while v != s:
                # Decrease residual capacity of the forward edge
                self.graph[prev_node[v]][prev_edge[v]][1] -= bottleneck
                # Increase residual capacity of the reverse edge
                rev_idx = self.graph[prev_node[v]][prev_edge[v]][3]
                self.graph[prev_node[v]][rev_idx][1] += bottleneck
                v = prev_node[v]

            total_flow += bottleneck
            total_cost += bottleneck * dist[t]

        return total_flow, total_cost
