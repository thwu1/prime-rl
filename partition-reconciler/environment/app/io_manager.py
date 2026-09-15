"""Partitioned filesystem IO manager for reading and writing asset data.

Storage layout for simple partition keys:
    base_path/asset_key/partition_key/data.json

Storage layout for multi-partition keys (containing '|'):
    base_path/asset_key/dim1=val1/dim2=val2/data.json
"""

import os
import json


class PartitionedIOManager:
    """Manages reading and writing partitioned data to the filesystem."""

    def __init__(self, base_path):
        self.base_path = base_path

    def _encode_partition_path(self, partition_key):
        """Convert a partition key string to a filesystem path component.

        For simple keys: returns the key itself.
        For multi-partition keys (containing '|'): splits into nested dirs.
        Example: 'day=2024-01-01|metric=temp' -> 'day=2024-01-01/metric=temp'
        """
        if "|" in partition_key:
            return os.path.join(*partition_key.split("|"))
        return partition_key

    def get_path(self, asset_key, partition_key):
        """Get the canonical storage path for an asset partition."""
        encoded = self._encode_partition_path(partition_key)
        return os.path.join(self.base_path, asset_key, encoded, "data.json")

    def write(self, asset_key, partition_key, data, run_id):
        """Write data for an asset partition."""
        path = os.path.join(self.base_path, asset_key, partition_key, "data.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"data": data, "run_id": run_id}, f)

    def read(self, asset_key, partition_key):
        """Read data for an asset partition."""
        path = self.get_path(asset_key, partition_key)
        if not os.path.exists(path):
            raise FileNotFoundError(f"No data at {path}")
        with open(path, "r") as f:
            record = json.load(f)
        return record["data"]

    def read_multiple(self, asset_key, partition_keys):
        """Read data for multiple partitions of an asset."""
        results = []
        for pk in partition_keys:
            results.append(self.read(asset_key, pk))
        return results
