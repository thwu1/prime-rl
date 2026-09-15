#!/usr/bin/env python3
"""Feature Flags - Runtime feature-flag evaluation.

Reads a YAML configuration file and exposes a simple ``is_enabled`` API
that other components use to gate code paths at runtime.  Flags support
an optional ``kill_switch`` field: when set to ``true`` the flag is forced
off regardless of the ``enabled`` field, providing a fast mechanism to
disable a broken code path in production.
"""
import logging
import yaml

logger = logging.getLogger('service_control.feature_flags')


class FeatureFlags:
    """Evaluate feature flags from a YAML config file."""

    def __init__(self, config_path):
        self.config_path = config_path
        self.flags = {}
        self._load(config_path)

    def _load(self, path):
        """Load flags from disk."""
        try:
            with open(path) as fh:
                data = yaml.safe_load(fh)
                if isinstance(data, dict):
                    self.flags = data
                    logger.info(f"Loaded {len(self.flags)} feature flags")
                else:
                    logger.warning("Feature-flag config is not a dict; ignoring")
        except Exception as exc:
            logger.error(f"Failed to load feature flags from {path}: {exc}")

    def is_enabled(self, flag_name):
        """Return True if *flag_name* should be active.

        Evaluation order:
          1. If the flag is unknown, default to **True** (fail-open for
             backwards compatibility with older configs).
          2. If ``kill_switch`` is set, the flag is forced **off**.
          3. Otherwise honour the ``enabled`` field (default True).
        """
        flag = self.flags.get(flag_name)
        if flag is None:
            # Unknown flag - default enabled for backwards compat
            return True
        if flag.get('kill_switch', False):
            logger.info(f"Flag '{flag_name}' disabled by kill switch")
            return False
        return flag.get('enabled', True)
