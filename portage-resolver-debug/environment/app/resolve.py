#!/usr/bin/env python3
"""CLI entry point for the Portage-style dependency resolver and upgrade planner."""

import sys

from resolver.database import PackageDB
from resolver.solver import Resolver
from resolver.planner import WorldUpgradePlanner


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} [--plan | [--use FLAG ...] atom ...]",
              file=sys.stderr)
        sys.exit(1)

    if sys.argv[1] == '--plan':
        planner = WorldUpgradePlanner(
            '/app/packages.db',
            '/app/portage'
        )
        plan = planner.generate_plan('/app/upgrade_plan.json')
        import json
        print(json.dumps(plan, indent=2))
        return

    use_flags: set[str] = set()
    atoms: list[str] = []
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == '--use':
            i += 1
            if i < len(sys.argv):
                use_flags.add(sys.argv[i])
        else:
            atoms.append(sys.argv[i])
        i += 1

    db = PackageDB('/app/packages.db')
    resolver = Resolver(db, use_flags)

    try:
        solution = resolver.resolve(atoms)
        print("Resolution successful:")
        for cp, ver, slot, sub in solution.packages:
            print(f"  {cp}-{ver}:{slot}/{sub}")
    except Exception as exc:
        print(f"Resolution failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
