"""Hardware configuration for GPU performance modeling."""
import json


class HardwareConfig:
    """Loads and stores GPU hardware parameters from a JSON config file."""

    def __init__(self, config_path):
        with open(config_path) as f:
            cfg = json.load(f)
        self.name = cfg["name"]
        self.num_sms = cfg["num_sms"]
        self.bandwidth_bytes_per_sec = cfg["bandwidth_bytes_per_sec"]
        self.memory_latency_sec = cfg["memory_latency_sec"]

    def bytes_in_flight(self):
        """Compute the minimum bytes that must be simultaneously in-flight
        to fully saturate the GPU's memory bandwidth, given the memory latency.

        This is a fundamental GPU performance metric derived from queuing theory.
        """
        raise NotImplementedError("bytes_in_flight not yet implemented")
