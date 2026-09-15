"""CLI entry point for the Puppet Forge Dependency Resolver."""

import sys
import json
import os

from .parser import parse_puppetfile
from .constraints import parse_constraint
from .solver import Solver
from .lockfile import write_lockfile


def main():
    args = sys.argv[1:]

    if not args or args[0] != 'resolve':
        print("Usage: python3 -m resolver resolve [--explain] [--graph <file>] <Puppetfile>",
              file=sys.stderr)
        sys.exit(1)

    args = args[1:]  # Remove 'resolve'

    explain = False
    graph_path = None
    puppetfile_path = None

    i = 0
    while i < len(args):
        if args[i] == '--explain':
            explain = True
            i += 1
        elif args[i] == '--graph':
            if i + 1 >= len(args):
                print("--graph requires a file path", file=sys.stderr)
                sys.exit(1)
            graph_path = args[i + 1]
            i += 2
        else:
            puppetfile_path = args[i]
            i += 1

    if puppetfile_path is None:
        print("Error: no Puppetfile specified", file=sys.stderr)
        sys.exit(1)

    forge_db = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'forge_db', 'modules.json'
    )

    # Parse Puppetfile
    entries = parse_puppetfile(puppetfile_path)

    # Build requirements for resolver — forge modules only
    requirements = []
    git_entries = []
    for entry in entries:
        if entry.source == 'git':
            git_entries.append(entry)
            continue
        if entry.constraint:
            constraints = parse_constraint(entry.constraint)
        else:
            constraints = []
        requirements.append((entry.name, constraints))

    # Resolve dependencies
    solver = Solver(forge_db)
    result = solver.resolve(requirements, explain=explain)

    # Output result as JSON
    print(json.dumps(result, indent=2))

    # Write lockfile and optional graph on success
    if result['status'] == 'ok':
        lockfile_path = puppetfile_path + '.lock'
        write_lockfile(lockfile_path, result['modules'], git_entries)

        if graph_path:
            dot_content = solver.generate_dot(result['modules'])
            with open(graph_path, 'w') as f:
                f.write(dot_content)

    sys.exit(0 if result['status'] == 'ok' else 1)


if __name__ == '__main__':
    main()
