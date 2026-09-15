"""Configuration loader for the evaluation pipeline.

Loads base configuration from TOML, applies YAML overrides, and
checks for environment variable overrides for deployment tuning.
"""

import os
import tomllib
import yaml
import math


def load_config(base_path='/app/config/main.toml',
                overrides_path='/app/config/overrides.yaml'):
    """Load evaluation configuration with override support.

    Base parameters come from the TOML file. The YAML overrides
    file allows deployment-specific tuning without modifying the
    base configuration. Environment variables provide the highest
    priority overrides for CI/deployment.

    Priority: env vars > YAML overrides > TOML base.
    """
    with open(base_path, 'rb') as f:
        config = tomllib.load(f)

    with open(overrides_path, 'r') as f:
        overrides = yaml.safe_load(f)

    if overrides:
        _deep_merge(config, overrides)

    _apply_env_overrides(config)

    return config


def _deep_merge(base, overrides):
    """Recursively merge overrides into base dict. Overrides win."""
    for key, value in overrides.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _apply_env_overrides(config):
    """Apply environment variable overrides for deployment tuning.

    Recognized variables:
      EVAL_NUM_RECALL_SAMPLES — override num_recall_samples
      EVAL_MAX_RANGE — override max_range_m
    """
    env_mappings = {
        'EVAL_NUM_RECALL_SAMPLES': ('evaluation', 'num_recall_samples', int),
        'EVAL_MAX_RANGE': ('evaluation', 'max_range_m', float),
    }
    for env_var, (section, key, converter) in env_mappings.items():
        val = os.environ.get(env_var)
        if val is not None:
            config.setdefault(section, {})[key] = converter(val)
