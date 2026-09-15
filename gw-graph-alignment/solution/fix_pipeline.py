#!/usr/bin/env python3
"""Apply all fixes to the OT pipeline."""


def fix_file(path, replacements):
    with open(path) as f:
        content = f.read()
    for old, new in replacements:
        if old not in content:
            raise ValueError(f"Pattern not found in {path}: {old!r}")
        content = content.replace(old, new)
    with open(path, 'w') as f:
        f.write(content)


# Fix 1: native/distances.c — sqrt bug
# The C function documents squared Euclidean but applies sqrt to sq_dist
fix_file('/app/native/distances.c', [
    ('out[i * m + j] = sqrt(sq_dist);',
     'out[i * m + j] = sq_dist;'),
])

# Fix 2: native/Makefile — ar creates static archive, need shared library
# Also need -fPIC for position-independent code
fix_file('/app/native/Makefile', [
    ('$(CC) $(CFLAGS) -c -o $@ $<',
     '$(CC) $(CFLAGS) -fPIC -c -o $@ $<'),
    ('\tar rcs $@ $<',
     '\t$(CC) -shared -o $@ $<'),
])

# Fix 3: sinkhorn.py — u_prev must be a copy, not an alias
# np.divide(..., out=u) modifies u in-place, making convergence check always zero
fix_file('/app/sinkhorn.py', [
    ('u_prev = u  # track previous iteration',
     'u_prev = u.copy()  # track previous iteration'),
])

# Fix 4: sinkhorn.py — barycenter update must use log(K @ v_k)
# u_k = bary/(K@v_k), so log(u_k) inverts the exponent, collapsing the barycenter
fix_file('/app/sinkhorn.py', [
    ('log_bary += weights[k] * np.log(np.maximum(u_k, 1e-300))',
     'log_bary += weights[k] * np.log(np.maximum(K @ v_k, 1e-300))'),
])

# Fix 5: gw_solver.py — _gwcost returns sum(constC*T) but should use sum(tens*T)
# constC is only the "constant" part; tens includes the cross term
fix_file('/app/gw_solver.py', [
    ('return np.sum(constC * T)',
     'return np.sum(tens * T)'),
])

# Fix 6: config.py — key mismatch and env override priority
# config.json uses "reg_epsilon" but loader looks for "regularization"
# OT_REG env var (1.0) overrides the intended value (0.1)
with open('/app/config.py', 'w') as f:
    f.write('''\
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

_KEY_ALIASES = {
    'reg_epsilon': 'regularization',
}


def load_config(path):
    """Load pipeline configuration from JSON file.

    File settings take precedence over environment variables.
    """
    with open(path) as f:
        raw = json.load(f)

    config = dict(_DEFAULTS)

    # Environment variable defaults (lower priority than file)
    _env_overrides = {
        'OT_REG': ('regularization', float),
        'OT_MAX_ITER': ('max_iter', int),
        'OT_TOL': ('tol', float),
    }
    for env_key, (config_key, cast_fn) in _env_overrides.items():
        val = os.environ.get(env_key)
        if val is not None:
            config[config_key] = cast_fn(val)

    # File settings override everything (handle legacy key names)
    for raw_key, raw_val in raw.items():
        config_key = _KEY_ALIASES.get(raw_key, raw_key)
        if config_key in _DEFAULTS:
            config[config_key] = raw_val

    return config
''')
