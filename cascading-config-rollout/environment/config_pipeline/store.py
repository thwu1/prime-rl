"""
Dual-source configuration store with versioned history.

Maintains two synchronized config sources for redundancy.
Primary is authoritative; secondary is kept in sync with possible
propagation delay.
"""
import json
import os
import time
import threading
from typing import Dict, List, Optional, Any


class ConfigSource:
    """Represents a single source of configuration truth."""

    def __init__(self, name: str, data_dir: str):
        self.name = name
        self.data_dir = data_dir
        self._lock = threading.Lock()
        os.makedirs(data_dir, exist_ok=True)

    def get_config(self, version: Optional[int] = None) -> Dict[str, Any]:
        """Get config at specified version, or latest if None."""
        with self._lock:
            versions = self._list_versions()
            if not versions:
                return {}
            target = version if version is not None else max(versions)
            path = os.path.join(self.data_dir, f"v{target}.json")
            if not os.path.exists(path):
                return {}
            with open(path) as f:
                return json.load(f)

    def put_config(self, config: Dict[str, Any]) -> int:
        """Store a new config version. Returns version number."""
        with self._lock:
            versions = self._list_versions()
            new_version = (max(versions) + 1) if versions else 1
            path = os.path.join(self.data_dir, f"v{new_version}.json")
            with open(path, 'w') as f:
                json.dump(config, f, indent=2)
            return new_version

    def _list_versions(self) -> List[int]:
        """List all available versions."""
        versions = []
        if not os.path.exists(self.data_dir):
            return versions
        for f in os.listdir(self.data_dir):
            if f.startswith('v') and f.endswith('.json'):
                try:
                    versions.append(int(f[1:-5]))
                except ValueError:
                    continue
        return sorted(versions)

    def get_all_versions(self) -> List[int]:
        with self._lock:
            return self._list_versions()


class DualSourceConfigStore:
    """Configuration store backed by two sources for redundancy.

    Primary source is authoritative. Secondary source is kept in sync
    for redundancy. Config reads should merge both sources.
    """

    def __init__(self, base_dir: str):
        self.primary = ConfigSource("primary", os.path.join(base_dir, "primary"))
        self.secondary = ConfigSource("secondary", os.path.join(base_dir, "secondary"))

    def initialize(self, config: Dict[str, Any]):
        """Initialize both sources with the same config."""
        self.primary.put_config(config)
        self.secondary.put_config(config)

    def update_config(self, config: Dict[str, Any], propagation_delay: float = 0):
        """Update config in primary, with optional delay to secondary.

        A nonzero propagation_delay simulates real-world replication lag.
        """
        self.primary.put_config(config)
        if propagation_delay > 0:
            def delayed_sync():
                time.sleep(propagation_delay)
                self.secondary.put_config(config)
            threading.Thread(target=delayed_sync, daemon=True).start()
        else:
            self.secondary.put_config(config)

    def get_primary_config(self) -> Dict[str, Any]:
        return self.primary.get_config()

    def get_secondary_config(self) -> Dict[str, Any]:
        return self.secondary.get_config()

    def get_all_historical_configs(self) -> List[Dict[str, Any]]:
        """Get all historical configs from primary source."""
        configs = []
        for v in self.primary.get_all_versions():
            configs.append(self.primary.get_config(v))
        return configs
