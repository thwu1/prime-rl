"""Dependency graph resolution using topological sort."""


class DependencyGraph:
    """Resolves migration execution order from declared dependencies."""

    def __init__(self):
        self._nodes = {}

    def add_node(self, node_id, dependencies=None):
        if node_id in self._nodes:
            raise ValueError(f"Duplicate node: {node_id}")
        self._nodes[node_id] = set(dependencies) if dependencies else set()

    def validate(self):
        for node_id, deps in self._nodes.items():
            for dep in deps:
                if dep not in self._nodes:
                    raise ValueError(
                        f"Migration '{node_id}' depends on unknown migration '{dep}'"
                    )
        for start_node in self._nodes:
            visited = set()
            if self._has_cycle(start_node, visited):
                raise ValueError(
                    f"Circular dependency detected involving '{start_node}'"
                )

    def _has_cycle(self, node, visited):
        if node in visited:
            return True
        visited.add(node)
        for dep in self._nodes.get(node, set()):
            if self._has_cycle(dep, visited):
                return True
        return False

    def resolve_order(self):
        self.validate()
        in_degree = {}
        adj = {}
        for node_id in self._nodes:
            in_degree[node_id] = len(self._nodes[node_id])
            adj[node_id] = []
        for node_id, deps in self._nodes.items():
            for dep in deps:
                adj[dep].append(node_id)
        queue = sorted([n for n in self._nodes if in_degree[n] == 0])
        result = []
        while queue:
            node = queue.pop(0)
            result.append(node)
            for dependent in sorted(adj[node]):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)
        if len(result) != len(self._nodes):
            raise ValueError("Circular dependency detected")
        return result
