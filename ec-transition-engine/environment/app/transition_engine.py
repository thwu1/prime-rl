"""EC Transition Engine — implement the TransitionEngine class.

Study the available library modules in /app/ to understand the
codec primitives, encoding matrix structure, and cluster operations.

"""

from cluster import Cluster


class TransitionEngine:
    """Erasure-code transition engine for a cluster file system."""

    def __init__(self, cluster: Cluster):
        self.cluster = cluster

    # ------------------------------------------------------------------
    # 1. encode_file
    # ------------------------------------------------------------------
    def encode_file(self, file_id: str, data: bytes,
                    k: int, m: int) -> dict:
        """Encode *data* with RS(k, m) and store shards on the cluster.

        All k+m shards must be placed on distinct nodes.
        Node placement: shard i goes to node (base + i) % num_nodes,
        where base = int(SHA256(file_id)[:8], 16) % num_nodes.

        Returns a dict:
            k              : int
            m              : int
            original_size  : int
            shard_locations: dict  {str(shard_idx): node_id}
            checksum       : str   SHA-256 hex digest of data
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 2. plan_transition
    # ------------------------------------------------------------------
    def plan_transition(self, file_id: str,
                        target_k: int, target_m: int) -> dict:
        """Plan an EC-scheme transition for *file_id*.

        The plan must minimize data movement when possible.

        Returns a dict:
            file_id            : str
            current_scheme     : (k, m) tuple
            target_scheme      : (target_k, target_m) tuple
            keep               : list of (shard_idx, node_id)
            delete             : list of (shard_idx, node_id)
            create             : list of (shard_idx, node_id, shard_bytes)
            data_movement_bytes: int  total bytes across create entries
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 3. execute_transition
    # ------------------------------------------------------------------
    def execute_transition(self, plan: dict) -> dict:
        """Apply a transition plan from plan_transition().

        Must write new shards before deleting old ones to maintain
        availability. Returns updated metadata (same shape as
        encode_file output).
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 4. reconstruct_read
    # ------------------------------------------------------------------
    def reconstruct_read(self, file_id: str,
                         failed_nodes: list = None) -> bytes:
        """Read *file_id*, tolerating node failures.

        If *failed_nodes* is None, treat all nodes with is_alive=False
        as failed. Returns the original file bytes.
        Raises ValueError if recovery is impossible or checksum
        verification fails.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 5. repair
    # ------------------------------------------------------------------
    def repair(self, file_id: str, failed_nodes: list) -> dict:
        """Repair a file after permanent node failures.

        Place replacement shards on available alive nodes.
        Returns updated metadata dict.
        Raises ValueError if too few shards survive for recovery.
        """
        raise NotImplementedError
