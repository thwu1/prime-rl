"""Cluster storage simulator.

Models a cluster of storage nodes.  Each node holds an in-memory
dictionary of shards keyed by (file_id, shard_index).  The Cluster
object also maintains per-file metadata.

"""


class NodeFailureError(Exception):
    pass


class ShardNotFoundError(Exception):
    pass


class Node:
    """A single storage node."""

    def __init__(self, node_id: int):
        self.node_id = node_id
        self.shards: dict = {}   # (file_id, shard_idx) -> bytes
        self.is_alive: bool = True

    def put_shard(self, file_id: str, shard_idx: int, data: bytes):
        self.shards[(file_id, shard_idx)] = data

    def get_shard(self, file_id: str, shard_idx: int) -> bytes:
        if not self.is_alive:
            raise NodeFailureError(f"node {self.node_id} is down")
        key = (file_id, shard_idx)
        if key not in self.shards:
            raise ShardNotFoundError(
                f"shard {key} not on node {self.node_id}")
        return self.shards[key]

    def delete_shard(self, file_id: str, shard_idx: int):
        self.shards.pop((file_id, shard_idx), None)

    def has_shard(self, file_id: str, shard_idx: int) -> bool:
        return (file_id, shard_idx) in self.shards


class Cluster:
    """A cluster of *num_nodes* storage nodes."""

    def __init__(self, num_nodes: int = 15):
        self.num_nodes = num_nodes
        self.nodes = [Node(i) for i in range(num_nodes)]
        self.file_metadata: dict = {}   # file_id -> metadata dict

    def get_node(self, node_id: int) -> Node:
        return self.nodes[node_id]

    def fail_node(self, node_id: int):
        self.nodes[node_id].is_alive = False

    def recover_node(self, node_id: int):
        self.nodes[node_id].is_alive = True

    def alive_node_ids(self) -> list:
        return [n.node_id for n in self.nodes if n.is_alive]

    def register_file(self, file_id: str, metadata: dict):
        self.file_metadata[file_id] = metadata

    def get_file_metadata(self, file_id: str):
        return self.file_metadata.get(file_id)
