"""Lockfile generation for resolved Puppet module dependencies."""

import json


def write_lockfile(path, forge_modules, git_entries):
    """Write a Puppetfile.lock with resolved forge and git modules.

    Args:
        path: Output lockfile path.
        forge_modules: List of {'name': ..., 'version': ...} dicts from the solver.
        git_entries: List of PuppetfileEntry objects with source='git'.
    """
    lockfile = {
        'forge_modules': forge_modules,
        'git_modules': [
            {
                'name': e.name,
                'git': e.git_url,
                'ref': e.git_ref,
            }
            for e in git_entries
        ],
    }
    with open(path, 'w') as f:
        json.dump(lockfile, f, indent=2)
        f.write('\n')
