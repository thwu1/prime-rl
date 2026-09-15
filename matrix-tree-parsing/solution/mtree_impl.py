"""Matrix-Tree Theorem dependency parsing module.

Implements probabilistic dependency parsing using the Matrix-Tree Theorem
(Kirchhoff's theorem for directed graphs).
"""

import numpy as np


def _build_kirchhoff(scores):
    """Build the Kirchhoff (Laplacian) matrix for directed spanning trees rooted at 0.

    K[j-1][j-1] = sum of all incoming arc weights to node j
    K[j-1][i-1] = -w(i->j) for i,j in {1..n}, i != j
    Root arcs w(0->j) contribute to diagonal only.
    """
    n = scores.shape[0] - 1
    weights = np.exp(scores)
    K = np.zeros((n, n))
    for j in range(1, n + 1):
        for i in range(n + 1):
            if i != j:
                K[j - 1][j - 1] += weights[i][j]
        for i in range(1, n + 1):
            if i != j:
                K[j - 1][i - 1] = -weights[i][j]
    return K


def log_partition(scores):
    """Log of the partition function Z = det(K) via slogdet for numerical stability."""
    scores = np.asarray(scores, dtype=np.float64)
    K = _build_kirchhoff(scores)
    sign, logdet = np.linalg.slogdet(K)
    if sign <= 0:
        raise ValueError("Kirchhoff matrix has non-positive determinant")
    return float(logdet)


def arc_marginals(scores):
    """Compute arc marginal probabilities P(i->j) via the Kirchhoff matrix inverse.

    For root arc (i=0):  P(0->j) = w(0,j) * K_inv[j-1, j-1]
    For non-root (i>=1): P(i->j) = w(i,j) * (K_inv[j-1, j-1] - K_inv[i-1, j-1])
    """
    scores = np.asarray(scores, dtype=np.float64)
    n = scores.shape[0] - 1
    K = _build_kirchhoff(scores)
    K_inv = np.linalg.inv(K)
    weights = np.exp(scores)

    marginals = np.zeros_like(scores)
    for i in range(n + 1):
        for j in range(1, n + 1):
            if i != j:
                if i == 0:
                    marginals[i][j] = weights[i][j] * K_inv[j - 1][j - 1]
                else:
                    marginals[i][j] = weights[i][j] * (
                        K_inv[j - 1][j - 1] - K_inv[i - 1][j - 1]
                    )

    return marginals


def entropy(scores):
    """Shannon entropy H = log(Z) - sum_{i,j} P(i->j) * S[i][j] (in nats)."""
    scores = np.asarray(scores, dtype=np.float64)
    n = scores.shape[0] - 1
    log_Z = log_partition(scores)
    marg = arc_marginals(scores)

    H = log_Z
    for i in range(n + 1):
        for j in range(1, n + 1):
            if i != j:
                H -= marg[i][j] * scores[i][j]

    return float(H)


def _find_cycle(heads, root):
    """Find a cycle in the head assignment. Returns list of nodes in cycle or None."""
    visited_global = set()
    for start in heads:
        if start in visited_global:
            continue
        path = []
        path_set = set()
        current = start
        while current != root and current not in visited_global and current not in path_set:
            path.append(current)
            path_set.add(current)
            if current in heads:
                current = heads[current]
            else:
                break

        if current in path_set:
            cycle_start = path.index(current)
            return path[cycle_start:]

        visited_global.update(path_set)

    return None


def _chu_liu_edmonds(nodes, root, edges):
    """Recursive Chu-Liu-Edmonds for maximum spanning arborescence.

    Args:
        nodes: set of node IDs
        root: root node ID
        edges: dict (i, j) -> score for arc from i to j

    Returns:
        dict {j: head_of_j} for all j != root in nodes
    """
    # Step 1: For each non-root node, find best incoming arc
    best_in = {}
    for j in nodes:
        if j == root:
            continue
        best_h = None
        best_s = float('-inf')
        for i in nodes:
            if i == j:
                continue
            if (i, j) in edges:
                if edges[(i, j)] > best_s:
                    best_s = edges[(i, j)]
                    best_h = i
        if best_h is None:
            raise ValueError(f"No incoming edge for node {j}")
        best_in[j] = (best_h, best_s)

    heads = {j: best_in[j][0] for j in best_in}

    # Step 2: Check for cycles
    cycle = _find_cycle(heads, root)

    if cycle is None:
        return heads

    cycle_set = set(cycle)

    # Step 3: Contract cycle into a single new node
    c_node = max(nodes) + 1
    new_nodes = (nodes - cycle_set) | {c_node}
    new_edges = {}

    # Edges from outside into the cycle (adjusted scores)
    in_map = {}
    for i in nodes:
        if i in cycle_set:
            continue
        best_j = None
        best_adj = float('-inf')
        for j in cycle:
            if (i, j) in edges:
                adjusted = edges[(i, j)] - best_in[j][1]
                if adjusted > best_adj:
                    best_adj = adjusted
                    best_j = j
        if best_j is not None:
            new_edges[(i, c_node)] = best_adj
            in_map[(i, c_node)] = best_j

    # Edges from the cycle to outside
    out_map = {}
    for j in nodes:
        if j in cycle_set or j == root:
            continue
        best_i = None
        best_s = float('-inf')
        for i in cycle:
            if (i, j) in edges:
                if edges[(i, j)] > best_s:
                    best_s = edges[(i, j)]
                    best_i = i
        if best_i is not None:
            new_edges[(c_node, j)] = best_s
            out_map[(c_node, j)] = best_i

    # Edges between non-cycle nodes
    for (i, j), s in edges.items():
        if i not in cycle_set and j not in cycle_set and i in new_nodes and j in new_nodes:
            new_edges[(i, j)] = s

    # Recurse on contracted graph
    sub_result = _chu_liu_edmonds(new_nodes, root, new_edges)

    # Step 4: Expand the contracted cycle
    final = {}

    c_head = sub_result.get(c_node)
    if c_head is not None:
        entry_j = in_map.get((c_head, c_node))
        if entry_j is None:
            raise ValueError("Cannot find entry point into cycle")
        for node in cycle:
            if node == entry_j:
                final[node] = c_head
            else:
                final[node] = heads[node]

    for j, h in sub_result.items():
        if j == c_node:
            continue
        if h == c_node:
            final[j] = out_map.get((c_node, j), h)
        else:
            final[j] = h

    return final


def map_tree(scores):
    """Maximum-weight arborescence via Chu-Liu-Edmonds.

    Returns list of length n+1 where result[j] is the head of node j,
    result[0] = -1.
    """
    scores = np.asarray(scores, dtype=np.float64)
    n = scores.shape[0] - 1
    nodes = set(range(n + 1))

    edge_dict = {}
    for i in range(n + 1):
        for j in range(1, n + 1):
            if i != j:
                edge_dict[(i, j)] = float(scores[i][j])

    result_heads = _chu_liu_edmonds(nodes, 0, edge_dict)

    heads = [-1] * (n + 1)
    for j, h in result_heads.items():
        heads[j] = int(h)
    return heads


def expected_attachment_score(scores, gold_heads):
    """Expected fraction of arcs matching gold_heads under the tree distribution."""
    scores = np.asarray(scores, dtype=np.float64)
    n = scores.shape[0] - 1
    marg = arc_marginals(scores)
    total = 0.0
    for j in range(1, n + 1):
        g = int(gold_heads[j])
        total += marg[g][j]
    return float(total / n)


def kl_divergence(scores_p, scores_q):
    """KL(P || Q) = -H(P) - sum_{i,j} P_p(i->j) * S_q[i][j] + log(Z_q)."""
    scores_p = np.asarray(scores_p, dtype=np.float64)
    scores_q = np.asarray(scores_q, dtype=np.float64)
    n = scores_p.shape[0] - 1

    H_p = entropy(scores_p)
    log_Z_q = log_partition(scores_q)
    marg_p = arc_marginals(scores_p)

    cross_term = 0.0
    for i in range(n + 1):
        for j in range(1, n + 1):
            if i != j:
                cross_term += marg_p[i][j] * scores_q[i][j]

    return float(-H_p - cross_term + log_Z_q)
