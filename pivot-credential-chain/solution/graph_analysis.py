#!/usr/bin/env python3
"""

Analyze the AD security graph to find the viable privilege escalation
path to Domain Admins, considering disabled accounts and inactive edges.
"""
import json
import os
import sys
from collections import defaultdict, deque


def find_viable_paths(graph_data):
    """Find all paths from enabled users to domain_admins via active edges only."""

    # Build adjacency list using only active edges
    adj = defaultdict(list)
    for edge in graph_data["edges"]:
        if edge.get("active", True):
            adj[edge["from"]].append(edge["to"])

    # Identify disabled/locked nodes
    disabled = set()
    for node in graph_data["nodes"]:
        if not node.get("enabled", True):
            disabled.add(node["id"])

    # Get all enabled user-type nodes
    users = [
        n["id"]
        for n in graph_data["nodes"]
        if n["type"] == "user" and n.get("enabled", True)
    ]

    target = "domain_admins"
    viable = []

    for user in users:
        # BFS from each enabled user to domain_admins
        queue = deque([(user, [user])])
        visited = {user}

        while queue:
            current, path = queue.popleft()

            if current == target:
                viable.append(path)
                break

            for neighbor in adj[current]:
                if neighbor not in visited and neighbor not in disabled:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

    return viable


def main():
    graph_path = sys.argv[1] if len(sys.argv) > 1 else "/app/enterprise/dc01/ad_graph.json"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "/app/results/viable_path.json"

    with open(graph_path) as f:
        graph = json.load(f)

    paths = find_viable_paths(graph)

    if not paths:
        print("[-] No viable privilege escalation paths found!", file=sys.stderr)
        sys.exit(1)

    # Use the first (should be only) viable path
    path = paths[0]
    print(f"[+] Viable escalation path: {' -> '.join(path)}")
    print(f"[+] Effective DA account: {path[0]}")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(path, f)

    return path


if __name__ == "__main__":
    main()
