"""Corrected Min-Cost Max-Flow solver using SPFA."""

from collections import deque


class MinCostMaxFlow:
    """Solves the minimum-cost maximum-flow problem on a directed graph."""

    def __init__(self, n):
        self.n = n
        self.graph = [[] for _ in range(n)]

    def add_edge(self, frm, to, cap, cost):
        self.graph[frm].append([to, cap, cost, len(self.graph[to])])
        self.graph[to].append([frm, 0, -cost, len(self.graph[frm]) - 1])

    def solve(self, s, t):
        total_flow = 0
        total_cost = 0
        INF = float('inf')

        while True:
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

            bottleneck = INF
            v = t
            while v != s:
                bottleneck = min(bottleneck, self.graph[prev_node[v]][prev_edge[v]][1])
                v = prev_node[v]

            v = t
            while v != s:
                self.graph[prev_node[v]][prev_edge[v]][1] -= bottleneck
                rev_idx = self.graph[prev_node[v]][prev_edge[v]][3]
                self.graph[v][rev_idx][1] += bottleneck
                v = prev_node[v]

            total_flow += bottleneck
            total_cost += bottleneck * dist[t]

        return total_flow, total_cost
