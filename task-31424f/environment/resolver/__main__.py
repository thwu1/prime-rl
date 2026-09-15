"""CLI entry point for the Puppet Forge Dependency Resolver."""

import sys
import json
import os

from .parser import parse_puppetfile
from .constraints import parse_constraint
from .solver import Solver
from .lockfile import write_lockfile


def main():
    if len(sys.argv) < 3 or sys.argv[1] != 'resolve':
        print("Usage: python3 -m resolver resolve <Puppetfile>", file=sys.stderr)
        sys.exit(1)

    puppetfile_path = sys.argv[2]
    forge_db = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'forge_db', 'modules.json'
    )

    # Parse Puppetfile
    entries = parse_puppetfile(puppetfile_path)

    # Build requirements for resolver
    requirements = []
    for entry in entries:
        if entry.constraint:
            constraints = parse_constraint(entry.constraint)
        else:
            constraints = []
        requirements.append((entry.name, constraints))

    # Resolve dependencies
    solver = Solver(forge_db)
    result = solver.resolve(requirements)

    # Output result as JSON
    print(json.dumps(result, indent=2))

    # Write lockfile on success
    if result['status'] == 'ok':
        lockfile_path = puppetfile_path + '.lock'
        git_entries = [e for e in entries if e.source == 'git']
        write_lockfile(lockfile_path, result['modules'], git_entries)

    sys.exit(0 if result['status'] == 'ok' else 1)


if __name__ == '__main__':
    main()
