import json
import os

_DEFAULTS = {
    'regularization': 1.0,
    'max_iter': 1000,
    'tol': 1e-9,
    'gw_max_iter': 1000,
    'gw_tol': 1e-9,
    'bary_max_iter': 100,
    'bary_tol': 1e-7,
}


def load_config(path):
    """Load pipeline configuration from JSON file."""
    with open(path) as f:
        raw = json.load(f)

    config = dict(_DEFAULTS)

    # Load parameters from file
    for key in _DEFAULTS:
        if key in raw:
            config[key] = raw[key]

    # Environment variable overrides
    _env_overrides = {
        'OT_REG': ('regularization', float),
        'OT_MAX_ITER': ('max_iter', int),
        'OT_TOL': ('tol', float),
    }
    for env_key, (config_key, cast_fn) in _env_overrides.items():
        val = os.environ.get(env_key)
        if val is not None:
            config[config_key] = cast_fn(val)

    return config
