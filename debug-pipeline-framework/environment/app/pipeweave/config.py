"""Configuration management with variable interpolation and environment overrides.

Supports nested dictionary access, ${variable} interpolation with dotted paths,
environment variable fallback, and deep-merge semantics.
"""
import re
import os
import copy
from collections import OrderedDict


class ConfigError(Exception):
    """Raised when configuration is invalid or contains circular references."""
    pass


class PipelineConfig:
    """Manages pipeline configuration with variable interpolation.

    Variable interpolation syntax:
      ${key}           - references a top-level config value
      ${section.key}   - references a nested config value via dotted path
      ${section2.key}  - identifiers may contain digits

    If a reference cannot be resolved from config, it falls back to
    environment variables (dots replaced with underscores, uppercased).
    Unresolvable references are left as-is.
    """

    _VAR_PATTERN = re.compile(r'\$\{([a-zA-Z_]+)\}')

    def __init__(self, data=None):
        self._data = OrderedDict(data or {})
        self._resolved_cache = None

    def get(self, dotted_key, default=None):
        """Retrieve a value using dotted path notation.

        Example: config.get('database.host') navigates into nested dicts.
        """
        keys = dotted_key.split('.')
        current = self._data
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current

    def set(self, dotted_key, value):
        """Set a value using dotted path notation, creating intermediate dicts."""
        keys = dotted_key.split('.')
        current = self._data
        for key in keys[:-1]:
            if key not in current or not isinstance(current[key], dict):
                current[key] = OrderedDict()
            current = current[key]
        current[keys[-1]] = value
        self._resolved_cache = None

    def resolve(self):
        """Resolve all variable interpolations and return the resolved dict.

        Results are cached until the config is modified.
        """
        if self._resolved_cache is not None:
            return copy.deepcopy(self._resolved_cache)
        self._resolved_cache = self._resolve_value(copy.deepcopy(self._data))
        return copy.deepcopy(self._resolved_cache)

    def _resolve_value(self, value, depth=0):
        """Recursively resolve interpolated variables in a value."""
        if depth > 20:
            raise ConfigError(
                "Maximum interpolation depth exceeded - possible circular reference"
            )
        if isinstance(value, dict):
            return OrderedDict(
                (k, self._resolve_value(v, depth)) for k, v in value.items()
            )
        elif isinstance(value, list):
            return [self._resolve_value(item, depth) for item in value]
        elif isinstance(value, str):
            return self._interpolate_string(value, depth)
        return value

    def _interpolate_string(self, text, depth):
        """Replace ${ref} patterns in a string with resolved values."""
        def replacer(match):
            ref_path = match.group(1)
            resolved = self.get(ref_path)
            if resolved is None:
                env_key = ref_path.replace('.', '_').upper()
                env_val = os.environ.get(env_key)
                if env_val is not None:
                    return env_val
                return match.group(0)
            if isinstance(resolved, str):
                return self._interpolate_string(resolved, depth + 1)
            return str(resolved)

        return self._VAR_PATTERN.sub(replacer, text)

    def merge(self, other_config):
        """Deep merge another config into this one; other takes precedence."""
        other_data = (other_config._data
                      if isinstance(other_config, PipelineConfig)
                      else other_config)
        self._deep_merge(self._data, other_data)
        self._resolved_cache = None
        return self

    @staticmethod
    def _deep_merge(base, override):
        for key, value in override.items():
            if (key in base and isinstance(base[key], dict)
                    and isinstance(value, dict)):
                PipelineConfig._deep_merge(base[key], value)
            else:
                base[key] = copy.deepcopy(value)

    def validate_required(self, required_keys):
        """Raise ConfigError if any required dotted keys are missing."""
        missing = [k for k in required_keys if self.get(k) is None]
        if missing:
            raise ConfigError(
                f"Missing required config keys: {', '.join(missing)}"
            )

    def to_dict(self):
        return copy.deepcopy(self._data)

    def flatten(self):
        """Flatten nested dict into dotted-path key -> value pairs."""
        result = OrderedDict()
        self._flatten_helper(self._data, [], result)
        return result

    def _flatten_helper(self, data, path, result):
        for key, value in data.items():
            current_path = path + [key]
            if isinstance(value, dict):
                self._flatten_helper(value, current_path, result)
            else:
                result['.'.join(current_path)] = value
