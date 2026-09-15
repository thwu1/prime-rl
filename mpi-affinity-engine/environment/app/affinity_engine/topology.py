"""Hardware topology representation and parsing."""

import json
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Core:
    """Represents a physical CPU core with its logical processor IDs."""
    physical_id: int
    logical_ids: List[int]
    numa_node_id: int
    socket_id: int

    @property
    def ht_enabled(self) -> bool:
        return len(self.logical_ids) > 1

    @property
    def primary_logical_id(self) -> int:
        return self.logical_ids[0]


@dataclass
class NumaNode:
    """Represents a NUMA memory domain containing a set of cores."""
    node_id: int
    socket_id: int
    cores: List[Core] = field(default_factory=list)

    @property
    def num_physical_cores(self) -> int:
        return len(self.cores)

    @property
    def num_logical_cpus(self) -> int:
        return sum(len(c.logical_ids) for c in self.cores)

    def get_all_logical_ids(self) -> List[int]:
        result = []
        for core in self.cores:
            result.extend(core.logical_ids)
        return sorted(result)


@dataclass
class Socket:
    """Represents a physical CPU socket containing one or more NUMA nodes."""
    socket_id: int
    numa_nodes: List[NumaNode] = field(default_factory=list)

    @property
    def num_physical_cores(self) -> int:
        return sum(nn.num_physical_cores for nn in self.numa_nodes)

    @property
    def cores(self) -> List[Core]:
        result = []
        for nn in self.numa_nodes:
            result.extend(nn.cores)
        return result


class Topology:
    """Hardware topology of a compute node."""

    def __init__(self, name: str, sockets: List[Socket],
                 numa_distances: Optional[List[List[int]]] = None):
        self.name = name
        self.sockets = sockets
        self.numa_distances = numa_distances
        self._build_lookups()

    def _build_lookups(self):
        self._core_by_physical = {}
        self._core_by_logical = {}
        self._numa_by_id = {}

        for socket in self.sockets:
            for numa_node in socket.numa_nodes:
                self._numa_by_id[numa_node.node_id] = numa_node
                for core in numa_node.cores:
                    self._core_by_physical[core.physical_id] = core
                    for lid in core.logical_ids:
                        self._core_by_logical[lid] = core

    @classmethod
    def from_json(cls, path: str) -> 'Topology':
        with open(path) as f:
            data = json.load(f)

        sockets = []
        for s_data in data['sockets']:
            numa_nodes = []
            for nn_data in s_data['numa_nodes']:
                cores = []
                for c_data in nn_data['cores']:
                    core = Core(
                        physical_id=c_data['physical_id'],
                        logical_ids=c_data['logical_ids'],
                        numa_node_id=nn_data['node_id'],
                        socket_id=s_data['socket_id']
                    )
                    cores.append(core)
                numa_node = NumaNode(
                    node_id=nn_data['node_id'],
                    socket_id=s_data['socket_id'],
                    cores=cores
                )
                numa_nodes.append(numa_node)
            socket = Socket(socket_id=s_data['socket_id'], numa_nodes=numa_nodes)
            sockets.append(socket)

        return cls(
            name=data.get('name', 'unknown'),
            sockets=sockets,
            numa_distances=data.get('numa_distances')
        )

    def get_core_by_physical(self, pid: int) -> Core:
        return self._core_by_physical[pid]

    def get_core_by_logical(self, lid: int) -> Core:
        return self._core_by_logical[lid]

    def get_numa_node(self, node_id: int) -> NumaNode:
        return self._numa_by_id[node_id]

    def get_all_cores(self) -> List[Core]:
        """Return all cores, iterating sockets then NUMA nodes in order."""
        cores = []
        for socket in self.sockets:
            for numa_node in socket.numa_nodes:
                cores.extend(numa_node.cores)
        return cores

    @property
    def num_physical_cores(self) -> int:
        return sum(s.num_physical_cores for s in self.sockets)

    @property
    def num_logical_cpus(self) -> int:
        return sum(len(c.logical_ids) for c in self.get_all_cores())

    @property
    def ht_enabled(self) -> bool:
        cores = self.get_all_cores()
        return any(c.ht_enabled for c in cores) if cores else False

    @property
    def num_sockets(self) -> int:
        return len(self.sockets)

    @property
    def num_numa_nodes(self) -> int:
        return sum(len(s.numa_nodes) for s in self.sockets)

    def numa_distance(self, node_a: int, node_b: int) -> int:
        if self.numa_distances is None:
            if node_a == node_b:
                return 10
            na = self._numa_by_id[node_a]
            nb = self._numa_by_id[node_b]
            if na.socket_id == nb.socket_id:
                return 21
            return 32
        return self.numa_distances[node_a][node_b]
