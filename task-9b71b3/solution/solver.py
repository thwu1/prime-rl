#!/usr/bin/env python3
"""Spack-style package constraint resolver."""

import json
import os
from collections import defaultdict


class Version:
    """Multi-component version with numeric comparison."""

    def __init__(self, s):
        self.raw = s
        self.parts = []
        for p in s.split("."):
            try:
                self.parts.append(int(p))
            except ValueError:
                self.parts.append(p)

    def __lt__(self, other):
        for a, b in zip(self.parts, other.parts):
            if type(a) != type(b):
                return isinstance(a, int)
            if a != b:
                return a < b
        return len(self.parts) < len(other.parts)

    def __eq__(self, other):
        return self.parts == other.parts

    def __le__(self, other):
        return self == other or self < other

    def __gt__(self, other):
        return other < self

    def __ge__(self, other):
        return not self < other

    def __hash__(self):
        return hash(tuple(self.parts))

    def __repr__(self):
        return self.raw


class VersionConstraint:
    """Version constraint: exact value, range, or unconstrained."""

    def __init__(self, exact=None, vmin=None, vmax=None):
        self.exact = Version(exact) if exact else None
        self.vmin = Version(vmin) if vmin else None
        self.vmax = Version(vmax) if vmax else None

    def allows(self, ver_str):
        v = Version(ver_str)
        if self.exact:
            return v == self.exact
        if self.vmin and v < self.vmin:
            return False
        if self.vmax and v > self.vmax:
            return False
        return True


class UnsatisfiableError(Exception):
    pass


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_version_str(s):
    """Parse a version string into a VersionConstraint."""
    if ":" in s:
        lo, hi = s.split(":", 1)
        return VersionConstraint(vmin=lo or None, vmax=hi or None)
    return VersionConstraint(exact=s)


def parse_single(text):
    """Parse one spec fragment: name[@ver][+var][~var]."""
    name = None
    vc = None
    variants = {}
    i = 0

    # Package name
    start = i
    while i < len(text) and text[i] not in "@+~ ":
        i += 1
    name = text[start:i]

    while i < len(text):
        ch = text[i]
        if ch == "@":
            i += 1
            start = i
            while i < len(text) and text[i] not in "+~ ":
                i += 1
            vc = parse_version_str(text[start:i])
        elif ch == "+":
            i += 1
            start = i
            while i < len(text) and text[i] not in "+~@ ":
                i += 1
            variants[text[start:i]] = True
        elif ch == "~":
            i += 1
            start = i
            while i < len(text) and text[i] not in "+~@ ":
                i += 1
            variants[text[start:i]] = False
        elif ch == " ":
            i += 1
            # Possibly a key=value variant
            start = i
            while i < len(text) and text[i] not in "+~@ ":
                i += 1
            token = text[start:i]
            if "=" in token:
                k, v = token.split("=", 1)
                variants[k] = v
        else:
            i += 1

    return name, vc, variants


def parse_query(query_str):
    """Parse full query with ^dependency constraints."""
    parts = query_str.split(" ^")
    main_name, main_vc, main_variants = parse_single(parts[0])
    dep_constraints = {}
    for dp in parts[1:]:
        dn, dvc, dvars = parse_single(dp)
        dep_constraints[dn] = (dvc, dvars)
    return main_name, main_vc, main_variants, dep_constraints


# ---------------------------------------------------------------------------
# Package repository
# ---------------------------------------------------------------------------

class Repo:
    def __init__(self, pkg_dir):
        self.packages = {}
        self.providers = defaultdict(list)
        for fn in sorted(os.listdir(pkg_dir)):
            if not fn.endswith(".json"):
                continue
            with open(os.path.join(pkg_dir, fn)) as f:
                pkg = json.load(f)
            self.packages[pkg["name"]] = pkg
            for virt in pkg.get("virtuals", []):
                self.providers[virt["name"]].append(
                    (pkg["name"], virt["provider_priority"])
                )
        for vn in self.providers:
            self.providers[vn].sort(key=lambda x: -x[1])

    def default_provider(self, virtual_name):
        providers = self.providers.get(virtual_name, [])
        return providers[0][0] if providers else None


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

class Resolver:
    def __init__(self, repo):
        self.repo = repo

    def resolve(self, query_str):
        name, vc, variants, dep_constraints = parse_query(query_str)

        # Identify virtual provider overrides from dep constraints
        virt_providers = {}
        for dc_name in dep_constraints:
            if dc_name in self.repo.packages:
                for virt in self.repo.packages[dc_name].get("virtuals", []):
                    virt_providers[virt["name"]] = dc_name

        resolved = {}
        try:
            self._resolve(
                name, vc, variants, resolved, virt_providers, dep_constraints
            )
            order = self._topo_sort(resolved, virt_providers)
            return {
                "query": query_str,
                "satisfiable": True,
                "specs": resolved,
                "build_order": order,
            }
        except UnsatisfiableError:
            return {"query": query_str, "satisfiable": False}

    # ------------------------------------------------------------------

    def _get_provider(self, virtual, virt_providers):
        if virtual in virt_providers:
            return virt_providers[virtual]
        return self.repo.default_provider(virtual)

    def _resolve(self, pkg_name, vc, var_overrides, resolved,
                 virt_providers, dep_constraints):
        """Recursively resolve a package and its dependencies."""

        if pkg_name in resolved:
            # Already resolved — verify compatibility
            if vc and not vc.allows(resolved[pkg_name]["version"]):
                raise UnsatisfiableError(
                    f"{pkg_name}@{resolved[pkg_name]['version']} "
                    f"violates new version constraint"
                )
            for vn, vv in var_overrides.items():
                cur = resolved[pkg_name]["variants"].get(vn)
                if cur is not None and cur != vv:
                    raise UnsatisfiableError(
                        f"Variant conflict on {pkg_name}.{vn}: "
                        f"{cur} vs {vv}"
                    )
            return

        pkg = self.repo.packages.get(pkg_name)
        if pkg is None:
            raise UnsatisfiableError(f"Unknown package: {pkg_name}")

        # Merge dep_constraints for this package
        effective_var_overrides = dict(var_overrides)
        if pkg_name in dep_constraints:
            dc_vc, dc_vars = dep_constraints[pkg_name]
            if dc_vc:
                vc = dc_vc
            effective_var_overrides.update(dc_vars)

        # Select best version (latest satisfying)
        best = None
        for vs in pkg["versions"]:
            if vc and not vc.allows(vs):
                continue
            if best is None or Version(vs) > Version(best):
                best = vs
        if best is None:
            raise UnsatisfiableError(
                f"No version of {pkg_name} satisfies constraints"
            )

        # Determine concrete variants
        variants = {}
        for vd in pkg.get("variants", []):
            vname = vd["name"]
            if vname in effective_var_overrides:
                variants[vname] = effective_var_overrides[vname]
            else:
                variants[vname] = vd["default"]

        # Check conflicts
        for conflict in pkg.get("conflicts", []):
            if self._conflict_matches(best, variants, conflict):
                raise UnsatisfiableError(
                    f"Conflict in {pkg_name}@{best}: "
                    f"{conflict.get('message', '')}"
                )

        resolved[pkg_name] = {"version": best, "variants": variants}

        # Resolve dependencies
        for dep in pkg.get("dependencies", []):
            # Conditional dependency
            if dep.get("when"):
                when_var = dep["when"].lstrip("+")
                if not variants.get(when_var, False):
                    continue

            dep_name = dep["name"]
            is_virtual = dep.get("virtual", False)

            if is_virtual:
                concrete = self._get_provider(dep_name, virt_providers)
                if concrete is None:
                    raise UnsatisfiableError(
                        f"No provider for virtual: {dep_name}"
                    )
                dep_name = concrete

            # Version constraint from package definition
            dep_vc = None
            if dep.get("version_min"):
                dep_vc = VersionConstraint(vmin=dep["version_min"])

            # Required variants
            dep_vars = {}
            if dep.get("required_variants"):
                dep_vars = dict(dep["required_variants"])

            self._resolve(
                dep_name, dep_vc, dep_vars, resolved,
                virt_providers, dep_constraints,
            )

    def _conflict_matches(self, version, variants, conflict):
        """Check if a concrete (version, variants) matches a conflict."""
        if "version_min" in conflict:
            if Version(version) < Version(conflict["version_min"]):
                return False
        if "version_max" in conflict:
            if Version(version) > Version(conflict["version_max"]):
                return False
        for vn, vv in conflict.get("variants", {}).items():
            if variants.get(vn) != vv:
                return False
        return True

    # ------------------------------------------------------------------
    # Topological sort (Kahn's algorithm, alphabetical tie-breaking)
    # ------------------------------------------------------------------

    def _topo_sort(self, resolved, virt_providers):
        # Build forward edges: edges[pkg] = set of pkgs it depends on
        edges = {pkg: set() for pkg in resolved}

        for pkg_name in resolved:
            pkg = self.repo.packages.get(pkg_name)
            if pkg is None:
                continue
            variants = resolved[pkg_name]["variants"]

            for dep in pkg.get("dependencies", []):
                if dep.get("when"):
                    wv = dep["when"].lstrip("+")
                    if not variants.get(wv, False):
                        continue

                dn = dep["name"]
                if dep.get("virtual"):
                    concrete = self._get_provider(dn, virt_providers)
                    if concrete and concrete in resolved:
                        dn = concrete
                    else:
                        continue

                if dn in resolved:
                    edges[pkg_name].add(dn)

        in_deg = {p: len(edges[p]) for p in resolved}
        queue = sorted(p for p in resolved if in_deg[p] == 0)
        order = []

        while queue:
            node = queue.pop(0)
            order.append(node)
            for pkg in list(edges.keys()):
                if node in edges[pkg]:
                    in_deg[pkg] -= 1
                    if in_deg[pkg] == 0:
                        # Binary insert to maintain sorted queue
                        lo, hi = 0, len(queue)
                        while lo < hi:
                            mid = (lo + hi) // 2
                            if queue[mid] < pkg:
                                lo = mid + 1
                            else:
                                hi = mid
                        queue.insert(lo, pkg)

        return order


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    repo = Repo("/app/packages")
    with open("/app/queries.json") as f:
        queries = json.load(f)

    results = []
    for q in queries:
        resolver = Resolver(repo)
        results.append(resolver.resolve(q))

    with open("/app/results.json", "w") as f:
        json.dump({"results": results}, f, indent=2)


if __name__ == "__main__":
    main()
