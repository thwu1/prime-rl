"""Backtracking dependency resolver for Puppet Forge modules."""

import sys
import json
from .constraints import parse_constraint, satisfies_all, SemVer


class Solver:
    """Resolves module dependencies using backtracking search."""

    def __init__(self, forge_db_path):
        with open(forge_db_path) as f:
            self.db = json.load(f)['modules']

    def get_versions(self, module_name):
        """Get available versions for a module, sorted descending."""
        if module_name not in self.db:
            print(f"Error: module '{module_name}' not found in forge database", file=sys.stderr)
            return None
        versions = list(self.db[module_name]['versions'].keys())
        versions.sort(key=lambda v: SemVer(v), reverse=True)
        return versions

    def get_dependencies(self, module_name, version):
        """Get dependencies for a specific module version."""
        return self.db[module_name]['versions'][version].get('dependencies', [])

    def resolve(self, requirements):
        """Resolve dependencies from a list of (name, constraint_list) tuples.

        Returns a dict with 'status' and either 'modules' or 'error_type'/'message'.
        """
        self.resolved = {}
        self.visited = set()

        if self._resolve(requirements):
            return {
                'status': 'ok',
                'modules': [
                    {'name': n, 'version': v}
                    for n, v in sorted(self.resolved.items())
                ]
            }
        return {
            'status': 'error',
            'error_type': 'unsatisfiable',
            'message': 'Could not find compatible module versions for all dependencies'
        }

    def _resolve(self, requirements):
        """Recursively resolve requirements using backtracking.

        Processes requirements head-first: resolve the first requirement
        (including its transitive deps) then continue with the remaining.
        """
        if not requirements:
            return True

        name, constraints = requirements[0]
        remaining = requirements[1:]

        # Check if already resolved
        if name in self.resolved:
            if satisfies_all(self.resolved[name], constraints):
                return self._resolve(remaining)
            return False

        # Look up available versions
        versions = self.get_versions(name)
        if versions is None:
            return False

        # Filter to compatible versions
        compatible = [v for v in versions if satisfies_all(v, constraints)]
        if not compatible:
            print(f"Warning: no version of '{name}' satisfies constraints", file=sys.stderr)
            return False

        for version in compatible:
            visit_key = f"{name}@{version}"
            if visit_key in self.visited:
                continue
            self.visited.add(visit_key)

            # Save state for backtracking
            saved = dict(self.resolved)
            self.resolved[name] = version

            # Get transitive dependencies for this version
            deps = self.get_dependencies(name, version)
            dep_reqs = [
                (dep['name'], parse_constraint(dep['version_requirement']))
                for dep in deps
            ]

            # Recurse: resolve deps then remaining requirements
            if self._resolve(dep_reqs + remaining):
                return True

            # Backtrack resolved but NOT visited
            self.resolved = saved

        return False
