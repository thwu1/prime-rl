
"""Synergy graph construction from empirical pass pair data.

Builds a directed graph where nodes are LLVM optimization passes and
edges represent empirically measured synergistic interactions. An edge
from pass A to pass B indicates that running A immediately before B
tends to produce effective optimization.
"""

from collections import defaultdict


def build_synergy_graph(synergy_pairs, threshold=0):
    """Build a directed adjacency-list graph from synergy pair data.

    Args:
        synergy_pairs: Dict mapping (pass_a, pass_b) tuples to synergy scores.
            Higher scores indicate stronger synergy between consecutive passes.
        threshold: Minimum synergy score to include an edge.

    Returns:
        Dict mapping pass names to sets of successor passes.
    """
    graph = defaultdict(set)
    for (pass_a, pass_b), score in synergy_pairs.items():
        if score >= threshold:
            graph[pass_b].add(pass_a)
    return dict(graph)


def get_successors(graph, pass_name):
    """Get the set of valid successor passes for a given pass."""
    return graph.get(pass_name, set())


def is_valid_sequence(graph, sequence):
    """Check whether a pass sequence follows synergy graph edges.

    Returns True if every consecutive pair (seq[i], seq[i+1]) has an
    edge in the synergy graph.
    """
    for i in range(len(sequence) - 1):
        successors = get_successors(graph, sequence[i])
        if sequence[i + 1] not in successors:
            return False
    return True


def find_paths(graph, start, max_length=10):
    """Find paths from a start node using DFS, up to max_length.

    Avoids cycles by not revisiting nodes within a single path.

    Returns:
        List of paths (each path is a list of pass names).
    """
    paths = []
    stack = [(start, [start])]
    while stack:
        node, path = stack.pop()
        if len(path) >= max_length:
            paths.append(path)
            continue
        successors = get_successors(graph, node)
        if not successors:
            paths.append(path)
            continue
        extended = False
        for succ in successors:
            if succ not in path:
                stack.append((succ, path + [succ]))
                extended = True
        if not extended:
            paths.append(path)
    return paths
