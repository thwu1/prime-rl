"""
Routing analysis engine.

"""


class RoutingEngine:
    """Routing engine for directed network graphs.

    Maintains a link-state database and computes forwarding decisions
    including primary paths, equal-cost multipath, and backup paths
    for fast reroute.
    """

    def __init__(self):
        """Initialize an empty routing engine."""
        raise NotImplementedError

    def update_link(self, src, dst, cost):
        """Add or update a directed link. Cost is a positive integer.
        Both endpoints are registered as nodes."""
        raise NotImplementedError

    def remove_link(self, src, dst):
        """Remove directed link. No-op if absent. Nodes persist."""
        raise NotImplementedError

    def get_nodes(self):
        """Return frozenset of all known node identifiers."""
        raise NotImplementedError

    def get_neighbors(self, node):
        """Return {neighbor: cost} for outgoing links from node."""
        raise NotImplementedError

    def shortest_path_distances(self, source):
        """Return {dest: distance} for all reachable nodes from source.
        Source excluded from results."""
        raise NotImplementedError

    def ecmp_next_hops(self, source):
        """Return {dest: frozenset(next_hops)} with all equal-cost
        first-hop nodes for each reachable destination. Source excluded."""
        raise NotImplementedError

    def compute_backup_nexthops(self, source):
        """Compute backup next-hops providing fast-reroute protection.

        For each reachable destination, identify which non-primary
        neighbors of source can serve as backup forwarding targets
        without routing traffic back through the failed element.

        Returns:
            {dest: {'link_protecting': frozenset,
                    'node_protecting': frozenset}}
            Reachable destinations only (excluding source).
        """
        raise NotImplementedError

    def backup_coverage(self, source):
        """Return backup path coverage statistics.

        Returns:
            {'link_protecting_pct': float (0-100),
             'node_protecting_pct': float (0-100),
             'unprotected': frozenset of unprotected destinations}
            Zero reachable destinations yields 100% coverage.
        """
        raise NotImplementedError

    def forwarding_table(self, source):
        """Compute complete forwarding table.

        Returns:
            {dest: {'cost': int,
                    'primary': frozenset,
                    'link_backup': frozenset,
                    'node_backup': frozenset}}
        """
        raise NotImplementedError

    def process_events(self, events, query_source):
        """Process topology events and return forwarding table after each.

        Event types:
        - ('add', src, dst, cost)
        - ('remove', src, dst)
        - ('add_symmetric', a, b, cost)
        - ('add_asymmetric', a, b, cost_ab, cost_ba)
        - ('remove_symmetric', a, b)

        Returns list of forwarding tables (one per event).
        """
        raise NotImplementedError
