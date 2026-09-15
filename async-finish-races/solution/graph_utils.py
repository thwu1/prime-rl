#!/usr/bin/env python3
"""Shared computation graph builder for the async-finish model."""

import json
from collections import defaultdict, deque


def build_graph(program):
    """
    Build a computation graph from an async-finish AST.
    Returns (steps, edges) where:
      steps: list of dicts {id, cost, reads: {var: aid}, writes: {var: aid}}
      edges: list of (from_id, to_id, edge_type) where edge_type is
             'spawn', 'continue', or 'join'
    """
    steps = []
    edges = []
    counter = [0]

    def new_step():
        sid = counter[0]
        counter[0] += 1
        step = {"id": sid, "cost": 0, "reads": {}, "writes": {}}
        steps.append(step)
        return step

    def process(node, cur, finish_scope):
        t = node["type"]
        if t == "seq":
            for item in node["body"]:
                cur = process(item, cur, finish_scope)
            return cur
        elif t == "compute":
            cur["cost"] += node["cost"]
            return cur
        elif t == "read":
            cur["reads"][node["var"]] = node["id"]
            return cur
        elif t == "write":
            cur["writes"][node["var"]] = node["id"]
            return cur
        elif t == "async":
            prev = cur
            async_first = new_step()
            async_last = process(node["child"], async_first, finish_scope)
            edges.append((prev["id"], async_first["id"], "spawn"))
            finish_scope.append(async_last)
            cont = new_step()
            edges.append((prev["id"], cont["id"], "continue"))
            return cont
        elif t == "finish":
            inner_scope = []
            last_of_body = process(node["body"], cur, inner_scope)
            after = new_step()
            for async_last in inner_scope:
                edges.append((async_last["id"], after["id"], "join"))
            edges.append((last_of_body["id"], after["id"], "continue"))
            return after
        else:
            raise ValueError(f"Unknown node type: {t}")

    initial = new_step()
    top_scope = []
    process(program, initial, top_scope)
    return steps, edges


def compute_work(steps):
    return sum(s["cost"] for s in steps)


def compute_span(steps, edges):
    """Longest weighted path in DAG via topological sort + DP."""
    adj = defaultdict(list)
    in_deg = defaultdict(int)
    for u, v, _ in edges:
        adj[u].append(v)
        in_deg[v] += 1

    queue = deque()
    for s in steps:
        if in_deg[s["id"]] == 0:
            queue.append(s["id"])

    topo = []
    while queue:
        u = queue.popleft()
        topo.append(u)
        for v in adj[u]:
            in_deg[v] -= 1
            if in_deg[v] == 0:
                queue.append(v)

    cost_of = {s["id"]: s["cost"] for s in steps}
    dist = {s["id"]: cost_of[s["id"]] for s in steps}

    for u in topo:
        for v in adj[u]:
            candidate = dist[u] + cost_of[v]
            if candidate > dist[v]:
                dist[v] = candidate

    return max(dist.values())


def detect_races(steps, edges):
    """Find data race pairs (unordered conflicting accesses)."""
    adj = defaultdict(list)
    for u, v, _ in edges:
        adj[u].append(v)

    reachable = {}
    for s in steps:
        visited = set()
        q = deque([s["id"]])
        while q:
            u = q.popleft()
            for v in adj[u]:
                if v not in visited:
                    visited.add(v)
                    q.append(v)
        reachable[s["id"]] = visited

    accesses = []
    for s in steps:
        for var, aid in s["reads"].items():
            accesses.append((s["id"], var, aid, False))
        for var, aid in s["writes"].items():
            accesses.append((s["id"], var, aid, True))

    by_var = defaultdict(list)
    for sid, var, aid, is_w in accesses:
        by_var[var].append((sid, aid, is_w))

    races = []
    for var, acc_list in by_var.items():
        for i in range(len(acc_list)):
            for j in range(i + 1, len(acc_list)):
                s1, id1, w1 = acc_list[i]
                s2, id2, w2 = acc_list[j]
                if not (w1 or w2):
                    continue
                if s2 in reachable[s1] or s1 in reachable[s2]:
                    continue
                races.append(sorted([id1, id2]))

    races.sort()
    return races


def load_trace(path):
    with open(path) as f:
        return json.load(f)
