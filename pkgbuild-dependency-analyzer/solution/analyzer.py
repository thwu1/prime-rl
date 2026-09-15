#!/usr/bin/env python3

"""
PKGBUILD Ecosystem Dependency Analyzer.

Parses Arch Linux PKGBUILD files, builds a dependency graph,
and outputs a JSON analysis report.
"""

import json
import os
import re
import sys
from collections import defaultdict
from itertools import combinations, product


# ---------------------------------------------------------------------------
# PKGBUILD Parsing
# ---------------------------------------------------------------------------

def strip_quotes(value):
    """Remove surrounding single or double quotes."""
    if len(value) >= 2:
        if (value[0] == "'" and value[-1] == "'") or \
           (value[0] == '"' and value[-1] == '"'):
            return value[1:-1]
    return value


def parse_bash_array(text):
    """Parse a bash array like ('a' 'b' 'c') into a list of strings."""
    text = text.strip()
    if text.startswith('('):
        text = text[1:]
    if text.endswith(')'):
        text = text[:-1]

    items = []
    for m in re.finditer(r"""'([^']*)'|"([^"]*)"|([^\s'")]+)""", text):
        item = m.group(1) if m.group(1) is not None else \
               m.group(2) if m.group(2) is not None else m.group(3)
        if item is not None and not item.startswith('#'):
            items.append(item)
    return items


def expand_variables(value, variables):
    """Expand ${var} and $var references in a string or list of strings."""
    if isinstance(value, list):
        return [expand_variables(v, variables) for v in value]

    def _replace(match):
        var_name = match.group(1) or match.group(2)
        replacement = variables.get(var_name, match.group(0))
        if isinstance(replacement, list):
            return ' '.join(str(r) for r in replacement)
        return str(replacement)

    return re.sub(r'\$\{(\w+)\}|\$(\w+)', _replace, str(value))


def _collect_multiline(lines, start_idx, initial_value):
    """Collect a potentially multi-line parenthesised value."""
    full = initial_value
    idx = start_idx
    while full.count('(') > full.count(')') and idx + 1 < len(lines):
        idx += 1
        full += ' ' + lines[idx].strip()
    return full, idx


def _skip_brace_block(lines, start_idx):
    """Skip from the opening '{' line to the matching '}'."""
    depth = lines[start_idx].count('{') - lines[start_idx].count('}')
    idx = start_idx
    while depth > 0 and idx + 1 < len(lines):
        idx += 1
        depth += lines[idx].count('{') - lines[idx].count('}')
    return idx


def parse_pkgbuild(filepath):
    """Parse a PKGBUILD file, returning (global_vars, functions)."""
    with open(filepath) as fh:
        content = fh.read()
    lines = content.split('\n')

    variables = {}
    functions = {}

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # skip blank / comment
        if not stripped or stripped.startswith('#'):
            i += 1
            continue

        # ---- function definition ----
        func_match = re.match(r'^(package(?:_[\w-]+)?|build|prepare|check|pkgver)\s*\(\)\s*\{', stripped)
        if func_match:
            func_name = func_match.group(1)
            body_lines = []
            depth = 1
            i += 1
            while i < len(lines) and depth > 0:
                depth += lines[i].count('{') - lines[i].count('}')
                if depth > 0:
                    body_lines.append(lines[i])
                else:
                    # partial line before closing brace
                    before_close = lines[i][:lines[i].rfind('}')]
                    if before_close.strip():
                        body_lines.append(before_close)
                i += 1
            functions[func_name] = '\n'.join(body_lines)
            continue

        # ---- other function (source etc.) – skip ----
        if re.match(r'^[\w_]+\s*\(\)\s*\{', stripped):
            i = _skip_brace_block(lines, i)
            i += 1
            continue

        # ---- variable assignment ----
        var_match = re.match(r'^(\w+)=(.*)', stripped)
        if var_match:
            var_name = var_match.group(1)
            var_value = var_match.group(2).strip()

            if var_value.startswith('('):
                var_value, i = _collect_multiline(lines, i, var_value)
                variables[var_name] = parse_bash_array(var_value)
            else:
                variables[var_name] = strip_quotes(var_value)
            i += 1
            continue

        i += 1

    return variables, functions


def parse_function_variables(func_body, global_vars):
    """Extract variable assignments from a package_*() function body."""
    local_vars = {}
    lines = func_body.split('\n')
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith('#'):
            i += 1
            continue

        var_match = re.match(r'^(\w+)=(.*)', stripped)
        if var_match:
            var_name = var_match.group(1)
            var_value = var_match.group(2).strip()
            if var_value.startswith('('):
                var_value, i = _collect_multiline(lines, i, var_value)
                parsed = parse_bash_array(var_value)
                local_vars[var_name] = expand_variables(parsed, global_vars)
            else:
                local_vars[var_name] = expand_variables(strip_quotes(var_value), global_vars)
            i += 1
            continue
        i += 1
    return local_vars


# ---------------------------------------------------------------------------
# Ecosystem Extraction
# ---------------------------------------------------------------------------

_OVERRIDABLE = {'pkgdesc', 'depends', 'provides', 'conflicts', 'optdepends'}
_LIST_FIELDS = {'depends', 'makedepends', 'provides', 'conflicts', 'optdepends', 'arch'}


def _ensure_list(val):
    if isinstance(val, str):
        return [val] if val else []
    if val is None:
        return []
    return list(val)


def extract_packages(ecosystem_dir):
    """Walk ecosystem_dir, parse each PKGBUILD, return {pkgname: metadata}."""
    packages = {}

    for entry in sorted(os.listdir(ecosystem_dir)):
        pkgbuild = os.path.join(ecosystem_dir, entry, 'PKGBUILD')
        if not os.path.isfile(pkgbuild):
            continue

        gvars, funcs = parse_pkgbuild(pkgbuild)

        pkgbase = gvars.get('pkgbase')
        pkgname_raw = gvars.get('pkgname')
        if isinstance(pkgname_raw, list):
            pkg_names = pkgname_raw
        else:
            pkg_names = [pkgname_raw]
        if pkgbase is None:
            pkgbase = pkg_names[0]

        pkgver = str(gvars.get('pkgver', '0'))
        pkgrel = str(gvars.get('pkgrel', '1'))
        epoch = int(gvars.get('epoch', 0))
        full_version = f"{epoch}:{pkgver}-{pkgrel}" if epoch else f"{pkgver}-{pkgrel}"

        for pname in pkg_names:
            pkg = {
                'pkgbase': pkgbase,
                'pkgver': pkgver,
                'pkgrel': pkgrel,
                'epoch': epoch,
                'full_version': full_version,
                'pkgdesc': expand_variables(gvars.get('pkgdesc', ''), gvars),
                'arch': _ensure_list(gvars.get('arch', ['any'])),
                'depends': _ensure_list(expand_variables(gvars.get('depends', []), gvars)),
                'makedepends': _ensure_list(expand_variables(gvars.get('makedepends', []), gvars)),
                'provides': _ensure_list(expand_variables(gvars.get('provides', []), gvars)),
                'conflicts': _ensure_list(expand_variables(gvars.get('conflicts', []), gvars)),
                'optdepends': _ensure_list(expand_variables(gvars.get('optdepends', []), gvars)),
            }

            # Override from package_NAME() or package()
            func_key = f'package_{pname}'
            if func_key in funcs:
                overrides = parse_function_variables(funcs[func_key], gvars)
            elif len(pkg_names) == 1 and 'package' in funcs:
                overrides = parse_function_variables(funcs['package'], gvars)
            else:
                overrides = {}

            for field in _OVERRIDABLE:
                if field in overrides:
                    val = overrides[field]
                    pkg[field] = _ensure_list(val) if field in _LIST_FIELDS else val

            packages[pname] = pkg

    return packages


# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------

def dep_name(dep_str):
    """Extract bare package name from a dependency string."""
    return re.split(r'[><=]', dep_str)[0]


def parse_constraint(dep_str):
    """Return (name, operator, version) from 'name>=1.0'."""
    m = re.match(r'^([\w.-]+?)([><=]+)([\w.]+)$', dep_str)
    if m:
        return m.group(1), m.group(2), m.group(3)
    return dep_str, None, None


def _ver_segments(v):
    parts = re.split(r'[.\-]', v)
    result = []
    for p in parts:
        if p.isdigit():
            result.append((0, int(p), p))
        else:
            result.append((1, 0, p))
    return result


def vercmp(a, b):
    """Simplified version comparison returning -1, 0, 1."""
    sa, sb = _ver_segments(a), _ver_segments(b)
    for (ta, na, sa_), (tb, nb, sb_) in zip(sa, sb):
        if ta != tb:
            return -1 if ta > tb else 1   # numeric (0) < alpha (1) reversed: num wins
        if ta == 0:  # both numeric
            if na != nb:
                return -1 if na < nb else 1
        else:  # both alpha
            if sa_ != sb_:
                return -1 if sa_ < sb_ else 1
    if len(sa) != len(sb):
        return -1 if len(sa) < len(sb) else 1
    return 0


def satisfies(available, op, required):
    if op is None:
        return True
    c = vercmp(available, required)
    return {
        '>=': c >= 0, '<=': c <= 0, '=': c == 0, '==': c == 0,
        '>': c > 0, '<': c < 0,
    }.get(op, True)


def find_providers(dep_str, packages):
    """Return list of package names that can satisfy dep_str."""
    name, op, ver = parse_constraint(dep_str)
    result = []
    for pname, pdata in packages.items():
        # direct name match
        if pname == name:
            if satisfies(pdata['pkgver'], op, ver):
                result.append(pname)
            continue
        # virtual provides
        for prov in pdata.get('provides', []):
            prov_name, _, prov_ver = parse_constraint(prov)
            if prov_name == name:
                if op is None:
                    result.append(pname)
                elif prov_ver and satisfies(prov_ver, op, ver):
                    result.append(pname)
    return result


def is_in_ecosystem(name, packages):
    """Check if a dependency name is provided by some ecosystem package."""
    if name in packages:
        return True
    for pdata in packages.values():
        for prov in pdata.get('provides', []):
            if dep_name(prov) == name:
                return True
    return False


# ---------------------------------------------------------------------------
# Issue detection
# ---------------------------------------------------------------------------

def detect_issues(packages):
    issues = []
    seen_conflict_pairs = set()

    # --- conflicts ---
    for pname, pdata in packages.items():
        for conflict_dep in pdata.get('conflicts', []):
            cname = dep_name(conflict_dep)
            # direct name
            if cname in packages and cname != pname:
                pair = tuple(sorted([pname, cname]))
                if pair not in seen_conflict_pairs:
                    seen_conflict_pairs.add(pair)
                    issues.append({
                        'type': 'CONFLICT',
                        'packages': list(pair),
                        'detail': f"{pname} conflicts with {cname}",
                    })
            # via provides
            for other_name, other_data in packages.items():
                if other_name == pname:
                    continue
                for prov in other_data.get('provides', []):
                    if dep_name(prov) == cname:
                        pair = tuple(sorted([pname, other_name]))
                        if pair not in seen_conflict_pairs:
                            seen_conflict_pairs.add(pair)
                            issues.append({
                                'type': 'CONFLICT',
                                'packages': list(pair),
                                'detail': f"{pname} conflicts with {other_name} (provides {cname})",
                            })

    # --- version mismatches ---
    for pname, pdata in packages.items():
        for dep_str in pdata.get('depends', []):
            dname, op, ver = parse_constraint(dep_str)
            if op is None:
                continue
            if not is_in_ecosystem(dname, packages):
                continue
            providers = find_providers(dep_str, packages)
            if not providers:
                # find best available version for the report
                avail = []
                if dname in packages:
                    avail.append(packages[dname]['pkgver'])
                for p in packages.values():
                    for prov in p.get('provides', []):
                        pn, _, pv = parse_constraint(prov)
                        if pn == dname and pv:
                            avail.append(pv)
                issues.append({
                    'type': 'VERSION_MISMATCH',
                    'package': pname,
                    'dependency': dep_str,
                    'available_version': max(avail, key=lambda v: _ver_segments(v)) if avail else 'none',
                })

    return issues


# ---------------------------------------------------------------------------
# Build order (topological sort on pkgbases)
# ---------------------------------------------------------------------------

def compute_build_order(packages, issues):
    # unsatisfiable packages
    unsatisfiable = {i['package'] for i in issues if i['type'] == 'VERSION_MISMATCH'}

    # map each pkgbase to its produced package names
    base_to_pkgs = defaultdict(list)
    for pname, pdata in packages.items():
        if pname not in unsatisfiable:
            base_to_pkgs[pdata['pkgbase']].append(pname)

    # also exclude pkgbases where ALL produced packages are unsatisfiable
    bases = {b for b, pkgs in base_to_pkgs.items() if pkgs}

    # map package name / virtual name → pkgbase
    name_to_base = {}
    for pname, pdata in packages.items():
        name_to_base[pname] = pdata['pkgbase']
        for prov in pdata.get('provides', []):
            pn = dep_name(prov)
            name_to_base.setdefault(pn, pdata['pkgbase'])

    # build edges: base → set of bases it depends on
    dep_graph = defaultdict(set)
    for base in bases:
        for pname in base_to_pkgs[base]:
            pdata = packages[pname]
            for d in pdata.get('depends', []) + pdata.get('makedepends', []):
                dn = dep_name(d)
                dep_base = name_to_base.get(dn)
                if dep_base and dep_base != base and dep_base in bases:
                    dep_graph[base].add(dep_base)

    # Kahn's algorithm
    in_deg = {b: 0 for b in bases}
    successors = defaultdict(set)
    for b, deps in dep_graph.items():
        for d in deps:
            successors[d].add(b)
            in_deg[b] += 1

    queue = sorted(b for b in bases if in_deg[b] == 0)
    order = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        for s in sorted(successors[node]):
            in_deg[s] -= 1
            if in_deg[s] == 0:
                queue.append(s)
        queue.sort()

    return order


# ---------------------------------------------------------------------------
# Installable groups (maximal independent sets w.r.t. conflicts)
# ---------------------------------------------------------------------------

def compute_installable_groups(packages, issues):
    unsatisfiable = {i['package'] for i in issues if i['type'] == 'VERSION_MISMATCH'}
    all_pkgs = sorted(p for p in packages if p not in unsatisfiable)

    # conflict adjacency
    conflict_adj = defaultdict(set)
    for issue in issues:
        if issue['type'] == 'CONFLICT':
            a, b = issue['packages']
            if a not in unsatisfiable and b not in unsatisfiable:
                conflict_adj[a].add(b)
                conflict_adj[b].add(a)

    conflicting = set(conflict_adj.keys())
    non_conflicting = [p for p in all_pkgs if p not in conflicting]

    # cluster conflicting packages by transitive conflict
    visited = set()
    clusters = []
    for pkg in sorted(conflicting):
        if pkg in visited:
            continue
        cluster = set()
        stack = [pkg]
        while stack:
            p = stack.pop()
            if p in visited:
                continue
            visited.add(p)
            cluster.add(p)
            for c in conflict_adj[p]:
                if c not in visited:
                    stack.append(c)
        clusters.append(sorted(cluster))

    # for each cluster, enumerate maximal independent sets
    def maximal_ind_sets(cluster):
        results = []
        for r in range(len(cluster), 0, -1):
            for subset in combinations(cluster, r):
                ss = set(subset)
                # independent?
                if any(ss & conflict_adj[p] for p in subset):
                    continue
                # maximal?
                if any(
                    not (conflict_adj[other] & ss)
                    for other in cluster if other not in ss
                ):
                    continue
                results.append(sorted(subset))
        return results if results else [[]]

    cluster_choices = [maximal_ind_sets(c) for c in clusters]

    groups = []
    for combo in (product(*cluster_choices) if cluster_choices else [()]):
        group = list(non_conflicting)
        for choice in combo:
            group.extend(choice)
        groups.append(sorted(group))

    # deduplicate
    seen = set()
    unique = []
    for g in groups:
        key = tuple(g)
        if key not in seen:
            seen.add(key)
            unique.append(g)

    return unique


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <ecosystem_dir>", file=sys.stderr)
        sys.exit(1)

    ecosystem_dir = sys.argv[1]
    packages = extract_packages(ecosystem_dir)
    issues = detect_issues(packages)
    build_order = compute_build_order(packages, issues)
    installable_groups = compute_installable_groups(packages, issues)

    report = {
        'packages': packages,
        'build_order': build_order,
        'issues': issues,
        'installable_groups': installable_groups,
    }
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
