"""
Dependency graph generator in Graphviz DOT format.

Produces a directed graph where:
  - Nodes represent packages in the merge set (upgrades + rebuilds)
  - Edges represent dependency relationships within the merge set
  - Node labels show the package cp and version transition
  - Edge labels show := for slot-operator dependencies
"""


class DependencyGraph:
    """Build and export a dependency graph in DOT format."""

    def __init__(self):
        self._nodes = {}   # cp -> {old_version, new_version, change_type}
        self._edges = []   # [(from_cp, to_cp, label)]

    def add_node(self, cp, old_version=None, new_version=None,
                 change_type='upgrade'):
        """Register a package node."""
        self._nodes[cp] = {
            'old_version': old_version,
            'new_version': new_version,
            'change_type': change_type,
        }

    def add_edge(self, from_cp, to_cp, label=''):
        """Register a dependency edge."""
        self._edges.append((from_cp, to_cp, label))

    def to_dot(self):
        """Render the graph as a DOT format string.

        Must produce valid Graphviz DOT parseable by ``dot -Tsvg``.
        Nodes should be labeled with the cp and version info.
        Edges should be labeled with := for slot-operator deps.
        """
        # TODO: implement DOT generation
        return 'digraph dependencies {\n}\n'

    def write_dot(self, path):
        """Write DOT representation to a file."""
        with open(path, 'w') as f:
            f.write(self.to_dot())
