"""
ASP-based package dependency resolver using the clingo constraint solver.

Translates package repository definitions and user spec strings into ASP
fact programs, invokes clingo with the encoding rules to find an optimal
solution, and parses the answer set back into a ResolvedDAG.
"""

import sys
sys.path.insert(0, '/app')

import os
import re
import clingo
from models import (
    PackageRepo, ConcreteSpec, ResolvedDAG,
    UnsatisfiableSpecError, ConflictError,
    parse_spec, parse_version_range,
    Version, VersionRange,
)
from typing import Any, Dict, List, Optional, Tuple


class Resolver:
    """Resolve package specs using ASP constraint solving via clingo."""

    def __init__(self, repo_path: str):
        self.repo = PackageRepo(repo_path)
        self.encoding_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'encoding.lp'
        )
        self._version_maps: Dict[str, Dict[str, str]] = {}
        self._reverse_maps: Dict[str, Dict[str, str]] = {}

    def resolve(self, spec_str: str) -> ResolvedDAG:
        """Resolve a spec string into a fully concrete dependency DAG.

        Raises UnsatisfiableSpecError or ConflictError when no valid
        resolution exists.
        """
        parsed = parse_spec(spec_str)
        facts = self._generate_facts(parsed)
        atoms = self._solve(facts)
        return self._build_dag(atoms)

    # ------------------------------------------------------------------
    # Fact generation
    # ------------------------------------------------------------------

    def _generate_facts(self, parsed: dict) -> str:
        """Translate the package repo and parsed spec into ASP facts."""
        lines: List[str] = []
        self._version_maps = {}
        self._reverse_maps = {}
        range_counter = 0
        range_defs: Dict[str, VersionRange] = {}
        range_targets: Dict[str, List[str]] = {}

        def new_range(targets: List[str], vr: VersionRange) -> str:
            nonlocal range_counter
            rid = f"r{range_counter}"
            range_counter += 1
            range_defs[rid] = vr
            range_targets[rid] = targets
            return rid

        # --- Package definitions ---
        for pkg_name, pkg in self.repo.packages.items():
            # Version facts with priority (0 = latest = most preferred)
            sorted_vers = sorted(pkg.versions)
            self._version_maps[pkg_name] = {}
            self._reverse_maps[pkg_name] = {}
            for idx, v in enumerate(sorted_vers):
                vid = f"v{idx}"
                self._version_maps[pkg_name][str(v)] = vid
                self._reverse_maps[pkg_name][vid] = str(v)
                pri = len(sorted_vers) - 1 - idx
                lines.append(f'avail("{pkg_name}",{vid}).')
                lines.append(f'vpri("{pkg_name}",{vid},{pri}).')

            # Variant definitions
            for var_name, var_def in pkg.variants.items():
                if var_def['type'] == 'bool':
                    default = "true" if var_def['default'] else "false"
                    lines.append(f'var_bool("{pkg_name}","{var_name}",{default}).')
                else:
                    lines.append(
                        f'var_enum("{pkg_name}","{var_name}","{var_def["default"]}").'
                    )

            # Dependency declarations
            for dep_idx, dep in enumerate(pkg.dependencies):
                did = f"d{dep_idx}"
                lines.append(f'dep("{pkg_name}","{dep.name}",{did}).')

                # Condition handling
                if dep.condition is not None:
                    lines.append(
                        f'dep_has_cond("{pkg_name}","{dep.name}",{did}).'
                    )
                    if dep.condition.startswith('+'):
                        var = dep.condition[1:]
                        lines.append(
                            f'dep_cond_var("{pkg_name}","{dep.name}",{did},"{var}",true).'
                        )
                    elif dep.condition.startswith('~'):
                        var = dep.condition[1:]
                        lines.append(
                            f'dep_cond_var("{pkg_name}","{dep.name}",{did},"{var}",false).'
                        )
                    elif dep.condition.startswith('@'):
                        vr = parse_version_range(dep.condition[1:])
                        rid = new_range([pkg_name], vr)
                        lines.append(
                            f'dep_cond_ver("{pkg_name}","{dep.name}",{did},{rid}).'
                        )

                # Dependency version range
                if dep.version_range is not None:
                    targets = (
                        self.repo.get_providers(dep.name)
                        if self.repo.is_virtual(dep.name)
                        else [dep.name]
                    )
                    rid = new_range(targets, dep.version_range)
                    lines.append(
                        f'dep_vrange("{pkg_name}","{dep.name}",{did},{rid}).'
                    )

                # Required variants on the dependency
                for rv_name, rv_val in dep.required_variants.items():
                    val_str = _val_to_asp(rv_val)
                    lines.append(
                        f'dep_req_var("{pkg_name}","{dep.name}",{did},"{rv_name}",{val_str}).'
                    )

            # Conflict declarations
            for conf_idx, conflict in enumerate(pkg.conflicts):
                cid = f"c{conf_idx}"
                lines.append(f'conflict("{pkg_name}",{cid}).')

                if conflict.version_range is not None:
                    rid = new_range([pkg_name], conflict.version_range)
                    lines.append(f'conflict_has_ver("{pkg_name}",{cid}).')
                    lines.append(f'conflict_ver("{pkg_name}",{cid},{rid}).')

                if conflict.variants:
                    lines.append(f'conflict_has_var("{pkg_name}",{cid}).')
                    for cv_name, cv_val in conflict.variants.items():
                        val_str = _val_to_asp(cv_val)
                        lines.append(
                            f'conflict_var("{pkg_name}",{cid},"{cv_name}",{val_str}).'
                        )

            # Virtual provider declarations
            for virtual in pkg.provides:
                lines.append(f'provides_virtual("{pkg_name}","{virtual}").')

        # --- Virtual package facts ---
        for virtual, providers in self.repo.virtuals.items():
            lines.append(f'virtual("{virtual}").')
            for pri, prov in enumerate(providers):
                lines.append(f'provider("{virtual}","{prov}",{pri}).')

        # --- Root request ---
        lines.append(f'root("{parsed["name"]}").')

        if parsed.get('version_range') is not None:
            rid = new_range([parsed['name']], parsed['version_range'])
            lines.append(f'vconstraint("{parsed["name"]}",{rid}).')

        for var_name, var_val in parsed.get('variants', {}).items():
            val_str = _val_to_asp(var_val)
            lines.append(
                f'user_variant("{parsed["name"]}","{var_name}",{val_str}).'
            )

        # --- User dependency constraints (^dep ...) ---
        for dep_name, dep_parsed in parsed.get('dep_constraints', {}).items():
            # Register provider override for all virtuals this package provides
            if dep_name in self.repo.packages:
                pkg = self.repo.packages[dep_name]
                for virtual in pkg.provides:
                    lines.append(f'user_provider("{virtual}","{dep_name}").')

            if dep_parsed.get('version_range') is not None:
                rid = new_range([dep_name], dep_parsed['version_range'])
                lines.append(f'vconstraint("{dep_name}",{rid}).')

            for var_name, var_val in dep_parsed.get('variants', {}).items():
                val_str = _val_to_asp(var_val)
                lines.append(
                    f'user_variant("{dep_name}","{var_name}",{val_str}).'
                )

        # --- Pre-compute version range satisfaction ---
        for rid, vr in range_defs.items():
            for pkg_name in range_targets[rid]:
                if pkg_name not in self._version_maps:
                    continue
                for ver_str, vid in self._version_maps[pkg_name].items():
                    if vr.contains(Version(ver_str)):
                        lines.append(f'v_in_range("{pkg_name}",{vid},{rid}).')

        return '\n'.join(lines)

    # ------------------------------------------------------------------
    # Clingo solving
    # ------------------------------------------------------------------

    def _solve(self, facts: str) -> List[str]:
        """Run clingo on the facts + encoding and return answer set atoms."""
        ctl = clingo.Control()
        ctl.add("base", [], facts)
        ctl.load(self.encoding_path)
        ctl.ground([("base", [])])

        best_atoms: Optional[List[str]] = None

        def on_model(model: clingo.Model) -> None:
            nonlocal best_atoms
            best_atoms = [str(a) for a in model.symbols(shown=True)]

        result = ctl.solve(on_model=on_model)

        if result.unsatisfiable:
            raise UnsatisfiableSpecError(
                "No valid resolution exists for the given constraints"
            )

        if best_atoms is None:
            raise UnsatisfiableSpecError("No solution found by clingo")

        return best_atoms

    # ------------------------------------------------------------------
    # Answer set parsing
    # ------------------------------------------------------------------

    def _build_dag(self, atoms: List[str]) -> ResolvedDAG:
        """Parse clingo answer set atoms into a ResolvedDAG."""
        specs: Dict[str, ConcreteSpec] = {}
        edge_set: set = set()
        variants: Dict[str, Dict[str, Any]] = {}

        for atom in atoms:
            m = re.match(r'(\w+)\((.+)\)', atom)
            if not m:
                continue
            pred = m.group(1)
            args = _parse_atom_args(m.group(2))

            if pred == 'selected':
                pkg, vid = args[0], args[1]
                ver_str = self._reverse_maps[pkg][vid]
                specs[pkg] = ConcreteSpec(
                    name=pkg, version=Version(ver_str)
                )

            elif pred == 'variant_val':
                pkg, var_name, val = args[0], args[1], args[2]
                if pkg not in variants:
                    variants[pkg] = {}
                variants[pkg][var_name] = _asp_to_val(val)

            elif pred == 'dep_edge':
                parent, child = args[0], args[1]
                edge_set.add((parent, child))

        # Merge variants into specs
        for pkg, var_dict in variants.items():
            if pkg in specs:
                specs[pkg].variants = var_dict

        edges = sorted(edge_set)
        build_order = _topological_sort(specs, edges)

        return ResolvedDAG(
            specs=specs,
            edges=edges,
            build_order=build_order,
        )


# ------------------------------------------------------------------
# Utility functions
# ------------------------------------------------------------------

def _val_to_asp(val: Any) -> str:
    """Convert a Python value to an ASP term."""
    if val is True:
        return 'true'
    if val is False:
        return 'false'
    return f'"{val}"'


def _asp_to_val(val: str) -> Any:
    """Convert an ASP term string back to a Python value."""
    if val == 'true':
        return True
    if val == 'false':
        return False
    return val


def _parse_atom_args(args_str: str) -> List[str]:
    """Parse ASP atom arguments, handling quoted strings."""
    args: List[str] = []
    current = ''
    in_quotes = False
    for ch in args_str:
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == ',' and not in_quotes:
            args.append(current.strip())
            current = ''
        else:
            current += ch
    if current.strip():
        args.append(current.strip())
    return args


def _topological_sort(
    specs: Dict[str, ConcreteSpec],
    edges: List[Tuple[str, str]],
) -> List[str]:
    """Kahn's algorithm with alphabetical tie-breaking."""
    in_degree: Dict[str, int] = {name: 0 for name in specs}
    adj: Dict[str, List[str]] = {name: [] for name in specs}

    for parent, child in edges:
        if parent in in_degree and child in adj:
            adj[child].append(parent)
            in_degree[parent] += 1

    queue = sorted(n for n in in_degree if in_degree[n] == 0)
    order: List[str] = []

    while queue:
        node = queue.pop(0)
        order.append(node)
        for neighbour in sorted(adj[node]):
            in_degree[neighbour] -= 1
            if in_degree[neighbour] == 0:
                queue.append(neighbour)
                queue.sort()

    if len(order) != len(specs):
        raise UnsatisfiableSpecError("Dependency cycle detected")

    return order
