"""Shard query router for Vitess-like sharded MySQL.

Routes queries to the correct shard database based on the keyspace_id
derived from the sharding key (channel_id).
"""

import yaml
from vhash import compute_keyspace_id, keyspace_id_in_range


def load_config(config_path='/app/config.yaml'):
    with open(config_path) as f:
        return yaml.safe_load(f)


def route_query(channel_id: int, config=None):
    """Determine which shard database a channel_id routes to.

    Returns the database name for the shard containing this channel_id.
    """
    if config is None:
        config = load_config()

    kid = compute_keyspace_id(channel_id)

    for shard in config['shards']:
        if keyspace_id_in_range(kid, shard['range_start'], shard['range_end']):
            return shard['database']

    raise ValueError(f"No shard found for channel_id={channel_id}, keyspace_id={kid.hex()}")
