"""Asset graph and partition reconciliation algorithm.

Determines which partitions of which assets need (re-)materialization
based on dependency ordering and materialization timestamps.
"""


class AssetNode:
    """A node in the asset dependency graph."""
    def __init__(self, key, partitions_def, deps=None):
        self.key = key
        self.partitions_def = partitions_def
        self.deps = deps or {}  # upstream_key -> PartitionMapping


class AssetGraph:
    """Directed acyclic graph of asset dependencies."""
    def __init__(self):
        self.nodes = {}

    def add_node(self, node):
        self.nodes[node.key] = node

    def get_upstream_keys(self, key):
        return list(self.nodes[key].deps.keys())

    def get_downstream_keys(self, key):
        return [
            node.key for node in self.nodes.values()
            if key in node.deps
        ]

    def topo_sort(self):
        """Return nodes in topological order (sources first)."""
        visited = set()
        result = []

        def dfs(key):
            if key in visited:
                return
            visited.add(key)
            result.append(key)
            for dep_key in self.get_upstream_keys(key):
                dfs(dep_key)

        for key in self.nodes:
            dfs(key)

        return result


class MaterializationRecord:
    """Record of a single partition materialization."""
    def __init__(self, run_id, timestamp):
        self.run_id = run_id
        self.timestamp = timestamp


class MaterializationState:
    """Tracks which partitions of which assets have been materialized."""
    def __init__(self):
        self._state = {}

    def mark_materialized(self, asset_key, partition_key, run_id, timestamp):
        self._state[(asset_key, partition_key)] = MaterializationRecord(run_id, timestamp)

    def is_materialized(self, asset_key, partition_key):
        return (asset_key, partition_key) in self._state

    def get_record(self, asset_key, partition_key):
        return self._state.get((asset_key, partition_key))

    def get_materialized_partitions(self, asset_key):
        return {pk for (ak, pk) in self._state if ak == asset_key}


class ReconciliationResult:
    """Result of reconciliation: partitions needing action."""
    def __init__(self):
        self._unmaterialized = {}
        self._stale = {}

    def add_unmaterialized(self, asset_key, partition_key):
        self._unmaterialized.setdefault(asset_key, set()).add(partition_key)

    def add_stale(self, asset_key, partition_key):
        self._stale.setdefault(asset_key, set()).add(partition_key)

    def get_unmaterialized(self, asset_key):
        return self._unmaterialized.get(asset_key, set())

    def get_stale(self, asset_key):
        return self._stale.get(asset_key, set())

    def get_all_actionable(self, asset_key):
        return self.get_unmaterialized(asset_key) | self.get_stale(asset_key)


class Reconciler:
    """Determines which partitions need (re-)materialization."""
    def __init__(self, graph, state):
        self.graph = graph
        self.state = state

    def reconcile(self):
        result = ReconciliationResult()
        order = self.graph.topo_sort()

        for asset_key in order:
            node = self.graph.nodes[asset_key]
            if node.partitions_def is None:
                continue

            for pk in node.partitions_def.get_keys():
                if not self.state.is_materialized(asset_key, pk):
                    result.add_unmaterialized(asset_key, pk)
                    continue

                if self._is_stale(node, pk):
                    result.add_stale(asset_key, pk)

        return result

    def _is_stale(self, node, partition_key):
        """Check if a materialized partition is stale due to upstream changes."""
        downstream_record = self.state.get_record(node.key, partition_key)
        if downstream_record is None:
            return False

        for upstream_key, mapping in node.deps.items():
            upstream_partition_keys = mapping.get_upstream_keys(partition_key)
            for upstream_pk in upstream_partition_keys:
                upstream_record = self.state.get_record(upstream_key, upstream_pk)
                if upstream_record is None:
                    continue
                if upstream_record.timestamp < downstream_record.timestamp:
                    return True

        return False
