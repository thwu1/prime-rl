"""
IR Optimizer — plugin-based optimization pipeline.

Reads /app/pipeline.toml to discover which passes to load from /app/passes/
and applies them iteratively until convergence or the configured iteration
limit is reached.

Each pass module must export:
    run(instructions: list[Instruction]) -> list[Instruction]
"""

import os
import sys
import importlib
import tomllib

from ir import Instruction

if '/app' not in sys.path:
    sys.path.insert(0, '/app')

_CONFIG_PATH = '/app/pipeline.toml'


def _load_config():
    if not os.path.isfile(_CONFIG_PATH):
        return {'max_iterations': 1, 'pass': []}
    with open(_CONFIG_PATH, 'rb') as f:
        return tomllib.load(f)


def optimize(instructions: list[Instruction]) -> list[Instruction]:
    """Run the configured optimization pipeline on the given instructions."""
    config = _load_config()
    max_iter = config.get('max_iterations', 10)

    pass_fns = []
    for entry in config.get('pass', []):
        if not entry.get('enabled', True):
            continue
        mod_name = entry.get('module')
        if not mod_name:
            continue
        try:
            mod = importlib.import_module(mod_name)
            if hasattr(mod, 'run') and callable(mod.run):
                pass_fns.append(mod.run)
        except ImportError:
            pass

    if not pass_fns:
        return list(instructions)

    current = list(instructions)
    for _ in range(max_iter):
        changed = False
        for fn in pass_fns:
            result = fn(list(current))
            if result != current:
                changed = True
                current = result
        if not changed:
            break
    return current
