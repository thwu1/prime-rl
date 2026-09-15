#!/usr/bin/env python3
"""
Solver for the Parallel Computation Graph Analyzer task.

Builds computation graphs from async-finish program ASTs,
then computes work, span, ideal parallelism, and data races.
"""

import json
from collections import defaultdict, deque


def build_graph(program):
    """
    Traverse the AST and construct the computation graph.
    Returns (steps, edges) where:
      steps: list of dicts {id, cost, reads: {var: aid}, writes: {var: aid}}
      edges: list of (from_id, to_id)
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
        """
        Process an AST node.
        cur: current step being built (accumulates compute/read/write)
        finish_scope: list collecting async-last-steps for innermost finish
        Returns the step that is "current" after processing this node.
        """
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
            # Create first step of async body
            async_first = new_step()
            # Process async body — asyncs inside inherit the same finish_scope
            async_last = process(node["child"], async_first, finish_scope)
            # Spawn edge: prev -> async body
            edges.append((prev["id"], async_first["id"]))
            # Register this async's last step in the enclosing finish scope
            finish_scope.append(async_last)
            # Continue edge: prev -> continuation
            cont = new_step()
            edges.append((prev["id"], cont["id"]))
            return cont

        elif t == "finish":
            inner_scope = []
            # Process finish body — current step flows into the body
            last_of_body = process(node["body"], cur, inner_scope)
            # After-finish step receives join edges
            after = new_step()
            for async_last in inner_scope:
                edges.append((async_last["id"], after["id"]))
            # Continue edge from end of body
            edges.append((last_of_body["id"], after["id"]))
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
    for u, v in edges:
        adj[u].append(v)
        in_deg[v] += 1

    # Kahn's topological sort
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
    """Find all data race pairs (unordered conflicting accesses)."""
    # Build adjacency for BFS reachability
    adj = defaultdict(list)
    for u, v in edges:
        adj[u].append(v)

    # Compute transitive closure via BFS from each node
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

    # Collect all memory accesses
    accesses = []
    for s in steps:
        for var, aid in s["reads"].items():
            accesses.append((s["id"], var, aid, False))
        for var, aid in s["writes"].items():
            accesses.append((s["id"], var, aid, True))

    # Group by variable
    by_var = defaultdict(list)
    for sid, var, aid, is_w in accesses:
        by_var[var].append((sid, aid, is_w))

    races = []
    for var, acc_list in by_var.items():
        for i in range(len(acc_list)):
            for j in range(i + 1, len(acc_list)):
                s1, id1, w1 = acc_list[i]
                s2, id2, w2 = acc_list[j]
                # At least one must be a write
                if not (w1 or w2):
                    continue
                # Check ordering
                if s2 in reachable[s1] or s1 in reachable[s2]:
                    continue
                races.append(sorted([id1, id2]))

    races.sort()
    return races


def analyze_trace(path):
    with open(path) as f:
        program = json.load(f)

    steps, edges = build_graph(program)
    work = compute_work(steps)
    span = compute_span(steps, edges)
    par = work / span if span > 0 else 0.0
    races = detect_races(steps, edges)

    return {
        "num_steps": len(steps),
        "num_edges": len(edges),
        "work": work,
        "span": span,
        "parallelism": par,
        "data_races": races,
    }


def main():
    results = {}
    for i in range(1, 5):
        results[f"trace{i}"] = analyze_trace(f"/app/traces/trace{i}.json")

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
