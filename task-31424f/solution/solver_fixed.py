"""Backtracking dependency resolver with cycle detection, conflict diagnostics, and graph generation."""

import sys
import json
from collections import defaultdict
from .constraints import parse_constraint, satisfies_all, SemVer


class Solver:
    """Resolves module dependencies using backtracking search."""

    def __init__(self, forge_db_path):
        with open(forge_db_path) as f:
            self.db = json.load(f)['modules']

    def _canonical_key(self, module_name):
        """Find the canonical DB key for a module name (case-insensitive)."""
        lower = module_name.lower()
        for key in self.db:
            if key.lower() == lower:
                return key
        return None

    def get_versions(self, module_name):
        """Get available versions for a module, sorted descending."""
        db_key = self._canonical_key(module_name)
        if db_key is None:
            print(f"Error: module '{module_name}' not found in forge database",
                  file=sys.stderr)
            return None
        versions = list(self.db[db_key]['versions'].keys())
        versions.sort(key=lambda v: SemVer(v), reverse=True)
        return versions

    def get_dependencies(self, module_name, version):
        """Get dependencies for a specific module version."""
        db_key = self._canonical_key(module_name)
        if db_key is None:
            return []
        return self.db[db_key]['versions'][version].get('dependencies', [])

    def resolve(self, requirements, explain=False):
        """Resolve dependencies from a list of (name, constraint_list) tuples.

        Returns a dict with 'status' and either 'modules' or error info.
        When explain=True and resolution fails (non-circular), includes 'conflicts'.
        """
        self.resolved = {}
        self.visited = set()
        self.constraint_log = []
        self._explain_mode = explain
        self._cycle = None

        # Wrap each requirement with an empty ancestor chain for cycle detection.
        # Internal format: (name, constraints, ancestor_chain)
        reqs = [(name, constraints, []) for name, constraints in requirements]

        if self._resolve(reqs):
            return {
                'status': 'ok',
                'modules': [
                    {'name': n, 'version': v}
                    for n, v in sorted(self.resolved.items())
                ]
            }

        # Resolution failed — determine why
        if self._cycle:
            return {
                'status': 'error',
                'error_type': 'circular_dependency',
                'message': f'Circular dependency detected: {" -> ".join(self._cycle)}',
                'cycle': self._cycle
            }

        result = {
            'status': 'error',
            'error_type': 'unsatisfiable',
            'message': 'Could not find compatible module versions for all dependencies'
        }

        if explain:
            result['conflicts'] = self._analyze_conflicts()

        return result

    def _resolve(self, requirements):
        """Recursively resolve requirements using backtracking.

        Each requirement is a (name, constraints, ancestor_chain) tuple where
        ancestor_chain tracks the dependency path from the top-level requirement
        down to the current module. This enables cycle detection that correctly
        distinguishes circular dependencies from diamond dependency patterns.
        """
        if not requirements:
            return True

        name, constraints, ancestor_chain = requirements[0]
        remaining = requirements[1:]

        # Normalize module name for case-insensitive matching
        canonical = name.lower()

        # Check for circular dependency BEFORE the already-resolved check.
        # A module in ancestor_chain is currently being resolved in our
        # dependency path — encountering it again means a cycle.
        # A module that is merely in self.resolved (but not an ancestor)
        # is a diamond dependency, which is valid.
        ancestor_modules = {e.split('@')[0] for e in ancestor_chain}
        if canonical in ancestor_modules:
            idx = next(i for i, e in enumerate(ancestor_chain)
                       if e.split('@')[0] == canonical)
            self._cycle = ancestor_chain[idx:] + [ancestor_chain[idx]]
            return False

        # Check if already resolved (diamond dependency case)
        if canonical in self.resolved:
            if satisfies_all(self.resolved[canonical], constraints):
                return self._resolve(remaining)
            return False

        # Look up available versions
        versions = self.get_versions(name)
        if versions is None:
            return False

        # Filter to compatible versions
        compatible = [v for v in versions if satisfies_all(v, constraints)]
        if not compatible:
            return False

        for version in compatible:
            visit_key = f"{canonical}@{version}"
            if visit_key in self.visited:
                continue
            self.visited.add(visit_key)

            # Save state for backtracking (both resolved AND visited)
            saved = dict(self.resolved)
            saved_visited = set(self.visited)
            self.resolved[canonical] = version

            # Build ancestor chain: current module added for its dependencies
            current_chain = ancestor_chain + [f"{canonical}@{version}"]

            # Get transitive dependencies for this version
            deps = self.get_dependencies(name, version)
            dep_reqs = []
            for dep in deps:
                dep_constraints = parse_constraint(dep['version_requirement'])
                # Dependencies inherit the current ancestor chain
                dep_reqs.append((dep['name'], dep_constraints, current_chain))
                if self._explain_mode:
                    self.constraint_log.append({
                        'module': dep['name'].lower(),
                        'constraint': dep['version_requirement'],
                        'required_by': f"{canonical}@{version}"
                    })

            # Recurse: resolve deps then remaining requirements.
            # Remaining requirements keep their OWN ancestor chains (not current_chain),
            # which is critical for distinguishing cycles from diamonds.
            if self._resolve(dep_reqs + remaining):
                return True

            # Backtrack both resolved and visited
            self.resolved = saved
            self.visited = saved_visited

        return False

    def _analyze_conflicts(self):
        """Analyze constraint log to find mutually unsatisfiable constraints."""
        by_module = defaultdict(list)
        for entry in self.constraint_log:
            by_module[entry['module']].append(entry)

        conflicts = []
        for mod, entries in by_module.items():
            all_constraints = []
            for entry in entries:
                all_constraints.extend(parse_constraint(entry['constraint']))

            versions = self.get_versions(mod)
            if versions is None:
                continue

            if not any(satisfies_all(v, all_constraints) for v in versions):
                seen = set()
                unique_entries = []
                for e in entries:
                    key = (e['required_by'], e['constraint'])
                    if key not in seen:
                        seen.add(key)
                        unique_entries.append(e)

                conflicts.append({
                    'module': mod,
                    'unsatisfiable_constraints': [
                        {'required_by': e['required_by'],
                         'constraint': e['constraint']}
                        for e in unique_entries
                    ]
                })

        return conflicts

    def generate_dot(self, resolved_modules):
        """Generate a DOT-format dependency graph from resolved modules."""
        lines = ['digraph dependencies {']
        lines.append('  rankdir=TB;')
        lines.append('  node [shape=box];')

        for mod in sorted(resolved_modules, key=lambda m: m['name']):
            node_id = f"{mod['name']}@{mod['version']}"
            lines.append(f'  "{node_id}";')

        for mod in sorted(resolved_modules, key=lambda m: m['name']):
            db_key = self._canonical_key(mod['name'])
            if db_key:
                deps = self.db[db_key]['versions'][mod['version']].get(
                    'dependencies', [])
                for dep in deps:
                    dep_lower = dep['name'].lower()
                    for resolved_mod in resolved_modules:
                        if resolved_mod['name'] == dep_lower:
                            src = f"{mod['name']}@{mod['version']}"
                            dst = f"{resolved_mod['name']}@{resolved_mod['version']}"
                            label = dep['version_requirement']
                            lines.append(
                                f'  "{src}" -> "{dst}" [label="{label}"];')
                            break

        lines.append('}')
        return '\n'.join(lines) + '\n'
