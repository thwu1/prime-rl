"""Basic coupled-placement storage engine.

Writes files using RS(k,m) erasure coding with coupled placement:
shard i is placed on node (base + i) % num_nodes, where *base* is
derived deterministically from the file_id.

This module is provided as a reference; the agent must implement the
more advanced TransitionEngine in transition_engine.py.

"""

import hashlib
from reed_solomon import encode
from cluster import Cluster


def _file_base(file_id: str, num_nodes: int) -> int:
    """Deterministic base-node for *file_id*."""
    h = int(hashlib.sha256(file_id.encode()).hexdigest()[:8], 16)
    return h % num_nodes


class StorageEngine:
    def __init__(self, cluster: Cluster):
        self.cluster = cluster

    def write_file(self, file_id: str, data: bytes,
                   k: int = 4, m: int = 2) -> dict:
        """Encode *data* as RS(k,m) and store across the cluster."""
        shards = encode(data, k, m)
        base = _file_base(file_id, self.cluster.num_nodes)

        shard_locations = {}
        for i, shard in enumerate(shards):
            node_id = (base + i) % self.cluster.num_nodes
            self.cluster.get_node(node_id).put_shard(file_id, i, shard)
            shard_locations[str(i)] = node_id

        metadata = {
            'k': k,
            'm': m,
            'original_size': len(data),
            'shard_locations': shard_locations,
            'checksum': hashlib.sha256(data).hexdigest(),
        }
        self.cluster.register_file(file_id, metadata)
        return metadata

    def read_file(self, file_id: str) -> bytes:
        """Read a file when all nodes are alive."""
        meta = self.cluster.get_file_metadata(file_id)
        if meta is None:
            raise FileNotFoundError(file_id)

        k = meta['k']
        parts = []
        for i in range(k):
            node_id = meta['shard_locations'][str(i)]
            parts.append(
                self.cluster.get_node(node_id).get_shard(file_id, i))

        result = b''.join(parts)[:meta['original_size']]
        if hashlib.sha256(result).hexdigest() != meta['checksum']:
            raise ValueError("data integrity check failed")
        return result
