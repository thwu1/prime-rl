#!/usr/bin/env python3
"""Fix all four bugs in the Puppet Forge dependency resolver pipeline.

Bug 1 (constraints.py): ~> X.Y pessimistic operator expands upper bound incorrectly.
  Wrong:  ~> 7.0 => >= 7.0.0 < 7.1.0  (bumps minor)
  Right:  ~> 7.0 => >= 7.0.0 < 8.0.0  (bumps major)

Bug 2 (solver.py): Module name lookup is case-sensitive, but forge metadata
  uses inconsistent casing (e.g., "Puppetlabs/Stdlib" vs "puppetlabs/stdlib").

Bug 3 (solver.py): The visited set is never restored on backtrack, so module
  versions tried in one resolution context are permanently skipped in later contexts.

Bug 4 (__main__.py): Git-sourced Puppetfile entries are passed to the forge
  resolver, which cannot find them and errors out.
"""

import os


def patch_file(path, replacements):
    """Apply exact string replacements to a file."""
    with open(path) as f:
        content = f.read()
    for old, new in replacements:
        if old not in content:
            raise ValueError(f"Patch target not found in {path}:\n{old[:80]}...")
        content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)


def fix_constraints():
    """Fix Bug 1: ~> X.Y upper bound should bump major, not minor."""
    path = '/app/resolver/constraints.py'
    with open(path) as f:
        content = f.read()

    # For 2-part pessimistic: bump major version, not minor
    content = content.replace(
        '            upper = f"{parts[0]}.{int(parts[1]) + 1}.0"',
        '            upper = f"{int(parts[0]) + 1}.0.0"',
        1  # only replace the first occurrence (the 2-part case)
    )

    with open(path, 'w') as f:
        f.write(content)


def fix_solver():
    """Fix Bugs 2 and 3 in the solver."""
    path = '/app/resolver/solver.py'
    with open(path) as f:
        content = f.read()

    # Bug 2: Replace case-sensitive get_versions with case-insensitive lookup
    content = content.replace(
        '''    def get_versions(self, module_name):
        """Get available versions for a module, sorted descending."""
        if module_name not in self.db:
            print(f"Error: module '{module_name}' not found in forge database", file=sys.stderr)
            return None
        versions = list(self.db[module_name]['versions'].keys())''',
        '''    def _canonical_key(self, module_name):
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
            print(f"Error: module '{module_name}' not found in forge database", file=sys.stderr)
            return None
        versions = list(self.db[db_key]['versions'].keys())'''
    )

    # Bug 2: Fix get_dependencies to use case-insensitive lookup
    content = content.replace(
        '''    def get_dependencies(self, module_name, version):
        """Get dependencies for a specific module version."""
        return self.db[module_name]['versions'][version].get('dependencies', [])''',
        '''    def get_dependencies(self, module_name, version):
        """Get dependencies for a specific module version."""
        db_key = self._canonical_key(module_name)
        if db_key is None:
            return []
        return self.db[db_key]['versions'][version].get('dependencies', [])'''
    )

    # Bug 2: Normalize names in _resolve for resolved dict and visited set
    content = content.replace(
        '''        # Check if already resolved
        if name in self.resolved:
            if satisfies_all(self.resolved[name], constraints):
                return self._resolve(remaining)
            return False''',
        '''        # Normalize module name for case-insensitive matching
        canonical = name.lower()

        # Check if already resolved
        if canonical in self.resolved:
            if satisfies_all(self.resolved[canonical], constraints):
                return self._resolve(remaining)
            return False'''
    )

    content = content.replace(
        '            visit_key = f"{name}@{version}"',
        '            visit_key = f"{canonical}@{version}"'
    )

    content = content.replace(
        '            self.resolved[name] = version',
        '            self.resolved[canonical] = version'
    )

    # Bug 3: Save and restore visited set on backtrack
    content = content.replace(
        '''            # Save state for backtracking
            saved = dict(self.resolved)''',
        '''            # Save state for backtracking
            saved = dict(self.resolved)
            saved_visited = set(self.visited)'''
    )

    content = content.replace(
        '''            # Backtrack resolved but NOT visited
            self.resolved = saved''',
        '''            # Backtrack both resolved and visited
            self.resolved = saved
            self.visited = saved_visited'''
    )

    with open(path, 'w') as f:
        f.write(content)


def fix_main():
    """Fix Bug 4: Filter git-sourced entries before forge resolution."""
    path = '/app/resolver/__main__.py'
    with open(path) as f:
        content = f.read()

    content = content.replace(
        '''    # Build requirements for resolver
    requirements = []
    for entry in entries:
        if entry.constraint:
            constraints = parse_constraint(entry.constraint)
        else:
            constraints = []
        requirements.append((entry.name, constraints))''',
        '''    # Build requirements for resolver — forge modules only
    requirements = []
    git_entries_collected = []
    for entry in entries:
        if entry.source == 'git':
            git_entries_collected.append(entry)
            continue
        if entry.constraint:
            constraints = parse_constraint(entry.constraint)
        else:
            constraints = []
        requirements.append((entry.name, constraints))'''
    )

    # Update the lockfile section to use the pre-collected git entries
    content = content.replace(
        '        git_entries = [e for e in entries if e.source == \'git\']',
        '        git_entries = git_entries_collected'
    )

    with open(path, 'w') as f:
        f.write(content)


if __name__ == '__main__':
    fix_constraints()
    print("Fixed Bug 1: pessimistic constraint expansion for ~> X.Y")
    fix_solver()
    print("Fixed Bug 2: case-insensitive module name lookup")
    print("Fixed Bug 3: visited set restoration on backtrack")
    fix_main()
    print("Fixed Bug 4: git-sourced entries filtered from forge resolution")
    print("All fixes applied.")
