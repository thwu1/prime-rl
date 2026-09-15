"""Load pipeline configuration from YAML.

Reads a pipeline.yaml file and constructs an AssetGraph with partition
definitions, mappings, and staleness mode configuration.
"""

import yaml
from partitions import (
    DailyPartitionDef, HourlyPartitionDef, StaticPartitionDef, MultiPartitionDef
)
from mappings import IdentityMapping, HourlyToDailyMapping, MultiToDailyMapping
from reconciler import AssetNode, AssetGraph


def load_pipeline(yaml_path):
    """Load pipeline config from YAML and return an AssetGraph."""
    with open(yaml_path) as f:
        config = yaml.safe_load(f)

    partition_defs = {}
    for asset_name, asset_config in config["assets"].items():
        partition_defs[asset_name] = _parse_partition_def(asset_config["partitions"])

    graph = AssetGraph()
    for asset_name, asset_config in config["assets"].items():
        deps = {}
        if "deps" in asset_config:
            for dep_name, dep_config in asset_config["deps"].items():
                mapping = _parse_mapping(
                    dep_config["mapping"],
                    partition_defs[dep_name],
                    partition_defs[asset_name],
                    dep_config
                )
                deps[dep_name] = mapping

        staleness_mode = asset_config.get("staleness_mode", "any")
        node = AssetNode(asset_name, partition_defs[asset_name], deps,
                         staleness_mode=staleness_mode)
        graph.add_node(node)

    return graph


def _parse_partition_def(config):
    """Parse a partition definition from config dict."""
    ptype = config["type"]
    if ptype == "daily":
        return DailyPartitionDef(config["start"], config["end"])
    elif ptype == "hourly":
        return HourlyPartitionDef(config["start"], config["end"])
    elif ptype == "static":
        return StaticPartitionDef(config["values"])
    elif ptype == "multi":
        dims = {}
        for dim_name, dim_config in config["dimensions"].items():
            dims[dim_name] = _parse_partition_def(dim_config)
        return MultiPartitionDef(dims)
    else:
        raise ValueError(f"Unknown partition type: {ptype}")


def _parse_mapping(mapping_type, upstream_def, downstream_def, config):
    """Parse a partition mapping from config dict."""
    if mapping_type == "identity":
        return IdentityMapping()
    elif mapping_type == "hourly_to_daily":
        return HourlyToDailyMapping(upstream_def, downstream_def)
    elif mapping_type == "multi_to_daily":
        time_dim = config.get("time_dimension", "day")
        return MultiToDailyMapping(upstream_def, downstream_def, time_dimension=time_dim)
    else:
        raise ValueError(f"Unknown mapping type: {mapping_type}")
