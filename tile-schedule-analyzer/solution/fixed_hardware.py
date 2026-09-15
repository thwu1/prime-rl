"""Hardware configuration for GPU performance modeling — corrected."""
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
        """Minimum bytes in-flight to saturate bandwidth (Little's Law).

        bytes_in_flight = bandwidth * latency
        """
        return self.bandwidth_bytes_per_sec * self.memory_latency_sec
