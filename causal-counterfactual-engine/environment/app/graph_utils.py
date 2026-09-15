
"""Graph utilities for causal inference on directed acyclic graphs."""

from collections import defaultdict, deque


def is_d_separated(parents_map, X_set, Y_set, Z_set):
    """Determine whether X_set and Y_set are d-separated given Z_set
    in the DAG defined by parents_map.

    A path between nodes in X_set and Y_set is *active* (d-connected) when:
      - Every non-collider on the path is NOT in Z_set, AND
      - Every collider on the path IS in Z_set or has a descendant in Z_set.

    If no active path exists, the sets are d-separated (conditionally
    independent given Z_set).

    Args:
        parents_map: dict mapping each node name to a list of its parent
            names. Every node in the graph must appear as a key (even if
            its parent list is empty).
        X_set: set of source node names.
        Y_set: set of target node names.
        Z_set: set of conditioning node names.

    Returns:
        True if X_set and Y_set are d-separated given Z_set
        (i.e., no active path exists), False otherwise.
    """
    raise NotImplementedError(
        "Implement d-separation testing for directed acyclic graphs."
    )


def compute_latent_projection(parents_map, children_map, hidden_vars, all_vars):
    """Compute the latent projection of a DAG onto its visible variables.

    When hidden (latent) variables are removed from the graph, any pair of
    visible variables that share a hidden common ancestor become connected
    by a bidirectional edge, representing unobserved confounding.

    Args:
        parents_map: dict mapping node -> list of parent names.
        children_map: dict mapping node -> list of child names.
        hidden_vars: set of hidden (latent) variable names to project out.
        all_vars: set of all variable names in the graph.

    Returns:
        A tuple (visible_parents, bidirectional_edges) where:
        - visible_parents: dict mapping each visible node to a list of its
          visible parents (directed edges that remain).
        - bidirectional_edges: set of frozenset({A, B}) pairs representing
          unobserved confounding between visible variables.
    """
    visible = all_vars - hidden_vars

    # Directed edges between visible variables
    visible_parents = {}
    for v in visible:
        visible_parents[v] = [p for p in parents_map.get(v, []) if p in visible]

    # Bidirectional edges from projecting out hidden variables
    bidirectional = set()
    for h in hidden_vars:
        visible_children = [c for c in children_map.get(h, []) if c in visible]
        for i in range(len(visible_children)):
            for j in range(i + 1, len(visible_children)):
                bidirectional.add(
                    frozenset({visible_children[i], visible_children[j]})
                )

    return visible_parents, bidirectional
