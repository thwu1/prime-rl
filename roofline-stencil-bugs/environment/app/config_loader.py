"""Load and normalize HPC machine configuration files.

Reads architecture-specific JSON configuration files and normalizes
all values to SI base units (bytes, FLOP/s) for use in performance
analysis models.
"""


import json
import os


def load_config(config_path):
    """Load a machine configuration from JSON and normalize to SI units.

    Config files specify bandwidth in GB/s and peak compute in GFLOP/s.
    This function converts everything to bytes/s and FLOP/s.

    Args:
        config_path: Path to a JSON machine configuration file.

    Returns:
        Dict with normalized machine parameters.
    """
    with open(config_path) as f:
        raw = json.load(f)

    config = {
        "name": raw["name"],
        "peak_flops": raw["peak_gflops"] * 1e9,
        "dram_bandwidth": raw["dram_bw_gbs"] * 1e6,
        "l2_bandwidth": raw["l2_bw_gbs"] * 1e6,
        "l2_size": raw["l2_size_kb"] * 1024,
        "cacheline_bytes": raw["cacheline_bytes"],
        "write_allocate": raw["write_allocate"],
        "elem_bytes": raw["elem_bytes"],
    }

    # Handle optional L3 cache (some architectures like A64FX lack L3)
    if raw.get("l3_bw_gbs") is not None:
        config["l3_bandwidth"] = raw["l3_bw_gbs"] * 1e6
        config["l3_size"] = raw["l3_size_mb"] * 1024 * 1024
    else:
        config["l3_bandwidth"] = None
        config["l3_size"] = None

    return config


def load_all_configs(config_dir="/app/configs"):
    """Load all machine configurations from a directory.

    Args:
        config_dir: Directory containing JSON config files.

    Returns:
        Dict mapping architecture name to normalized config.
    """
    configs = {}
    for fname in sorted(os.listdir(config_dir)):
        if fname.endswith(".json"):
            path = os.path.join(config_dir, fname)
            cfg = load_config(path)
            configs[cfg["name"]] = cfg
    return configs
