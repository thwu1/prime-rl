#!/usr/bin/env python3
"""
PKGBUILD Ecosystem Toolkit — Analyzer

Reads bash-extracted metadata, performs graph analysis, implements vercmp,
generates .SRCINFO files, simulates installation, and renders dependency graph.
"""


import heapq
import json
import os
import re
import subprocess
from collections import defaultdict


# ── Load Extracted Data ──────────────────────────────────────────────────────

def load_extracted():
    with open("/app/output/extracted.json") as f:
        return json.load(f)


# ── Build Package Map ────────────────────────────────────────────────────────

def build_packages(extracted):
    packages = {}
    for pkgdata in extracted:
        pkgbase = pkgdata["pkgbase"]
        pkgver = pkgdata["pkgver"]
        pkgrel = pkgdata["pkgrel"]
        epoch = pkgdata["epoch"]

        version = f"{pkgver}-{pkgrel}"
        if epoch:
            version = f"{epoch}:{version}"

        g_depends = pkgdata.get("depends", [])
        g_provides = pkgdata.get("provides", [])
        g_conflicts = pkgdata.get("conflicts", [])
        g_makedepends = pkgdata.get("makedepends", [])
        g_pkgdesc = pkgdata.get("pkgdesc", "")

        for pkg_ov in pkgdata.get("packages", []):
            pname = pkg_ov["name"]
            if pkg_ov.get("has_override", False):
                pkg = {
                    "base": pkgbase,
                    "version": version,
                    "depends": pkg_ov.get("depends", g_depends),
                    "makedepends": g_makedepends,
                    "provides": pkg_ov.get("provides", g_provides),
                    "conflicts": pkg_ov.get("conflicts", g_conflicts),
                    "pkgdesc": pkg_ov.get("pkgdesc", g_pkgdesc),
                }
            else:
                pkg = {
                    "base": pkgbase,
                    "version": version,
                    "depends": g_depends,
                    "makedepends": g_makedepends,
                    "provides": g_provides,
                    "conflicts": g_conflicts,
                    "pkgdesc": g_pkgdesc,
                }
            packages[pname] = pkg
    return packages


# ── Graph Utilities ──────────────────────────────────────────────────────────

def dep_name(dep_str):
    return re.split(r"[><=]", dep_str)[0]


def build_providers_map(packages):
    providers = defaultdict(list)
    for pname, info in packages.items():
        for prov in info.get("provides", []):
            vname = dep_name(prov)
            providers[vname].append(pname)
    return dict(providers)


def find_conflict_groups(packages):
    edges = set()
    for pname, info in packages.items():
        for c in info.get("conflicts", []):
            cname = dep_name(c)
            if cname in packages:
                edges.add(tuple(sorted((pname, cname))))
    groups = []
    for a, b in sorted(edges):
        b_conflicts = {dep_name(c) for c in packages[b].get("conflicts", [])}
        if a in b_conflicts:
            groups.append([a, b])
    return groups


def build_dep_graph(packages, providers):
    graph = defaultdict(set)
    for pname, info in packages.items():
        for d in info.get("depends", []):
            dn = dep_name(d)
            if dn in packages:
                graph[pname].add(dn)
            elif dn in providers:
                for p in providers[dn]:
                    graph[pname].add(p)
    return graph


def find_cycles(graph, packages):
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in packages}
    cycles = []

    def dfs(node, path):
        color[node] = GRAY
        path.append(node)
        for nb in sorted(graph.get(node, [])):
            if color[nb] == GRAY:
                idx = path.index(nb)
                cycles.append(sorted(path[idx:]))
            elif color[nb] == WHITE:
                dfs(nb, path)
        path.pop()
        color[node] = BLACK

    for node in sorted(packages):
        if color[node] == WHITE:
            dfs(node, [])

    seen = set()
    unique = []
    for c in cycles:
        key = frozenset(c)
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def topological_sort(graph, packages, cyclic_nodes):
    """Kahn's algorithm with min-heap for alphabetical tiebreaking."""
    remaining = sorted(p for p in packages if p not in cyclic_nodes)
    in_deg = {p: 0 for p in remaining}
    adj = defaultdict(list)

    for pkg in remaining:
        for d in graph.get(pkg, []):
            if d in in_deg:
                adj[d].append(pkg)
                in_deg[pkg] += 1

    heap = sorted(p for p in remaining if in_deg[p] == 0)
    heapq.heapify(heap)
    order = []

    while heap:
        node = heapq.heappop(heap)
        order.append(node)
        for nb in adj[node]:
            in_deg[nb] -= 1
            if in_deg[nb] == 0:
                heapq.heappush(heap, nb)
    return order


# ── Vercmp (pacman algorithm) ────────────────────────────────────────────────

def _split_segments(version):
    """Split version into runs of digits or alpha characters."""
    segments = []
    current = ""
    current_type = None
    for ch in version:
        if ch.isdigit():
            if current_type == "digit":
                current += ch
            else:
                if current:
                    segments.append(current)
                current = ch
                current_type = "digit"
        elif ch.isalpha():
            if current_type == "alpha":
                current += ch
            else:
                if current:
                    segments.append(current)
                current = ch
                current_type = "alpha"
        else:
            if current:
                segments.append(current)
                current = ""
                current_type = None
    if current:
        segments.append(current)
    return segments


def _compare_versions(a, b):
    seg_a = _split_segments(a)
    seg_b = _split_segments(b)
    for i in range(max(len(seg_a), len(seg_b))):
        if i >= len(seg_a):
            return -1
        if i >= len(seg_b):
            return 1
        sa, sb = seg_a[i], seg_b[i]
        is_num_a = sa.isdigit()
        is_num_b = sb.isdigit()
        if is_num_a and is_num_b:
            na, nb = int(sa), int(sb)
            if na != nb:
                return 1 if na > nb else -1
        elif is_num_a:
            return 1
        elif is_num_b:
            return -1
        else:
            if sa != sb:
                return 1 if sa > sb else -1
    return 0


def vercmp(a, b):
    """Compare two version strings using pacman's vercmp algorithm."""
    if a == b:
        return 0
    # Extract epoch
    if ":" in a:
        epoch_a, ver_a = int(a.split(":")[0]), a.split(":", 1)[1]
    else:
        epoch_a, ver_a = 0, a
    if ":" in b:
        epoch_b, ver_b = int(b.split(":")[0]), b.split(":", 1)[1]
    else:
        epoch_b, ver_b = 0, b

    if epoch_a != epoch_b:
        return 1 if epoch_a > epoch_b else -1

    # Split version-release
    if "-" in ver_a:
        vp_a, rel_a = ver_a.rsplit("-", 1)
    else:
        vp_a, rel_a = ver_a, None
    if "-" in ver_b:
        vp_b, rel_b = ver_b.rsplit("-", 1)
    else:
        vp_b, rel_b = ver_b, None

    result = _compare_versions(vp_a, vp_b)
    if result != 0:
        return result
    if rel_a is not None and rel_b is not None:
        return _compare_versions(rel_a, rel_b)
    elif rel_a is not None:
        return 1
    elif rel_b is not None:
        return -1
    return 0


# ── Install Simulation ───────────────────────────────────────────────────────

def simulate_install(targets, packages, providers_map):
    install_set = set()
    provider_selections = {}

    def resolve(pkg_name):
        if pkg_name in install_set:
            return
        install_set.add(pkg_name)
        for dep_str in packages[pkg_name].get("depends", []):
            dn = dep_name(dep_str)
            if dn in packages:
                resolve(dn)
            elif dn in providers_map:
                if dn not in provider_selections:
                    candidates = providers_map[dn]
                    if len(candidates) == 1:
                        provider_selections[dn] = candidates[0]
                    else:
                        best, best_ver = None, None
                        for cand in candidates:
                            for prov in packages[cand].get("provides", []):
                                prov_name = dep_name(prov)
                                if prov_name == dn and "=" in prov:
                                    prov_ver = prov.split("=", 1)[1]
                                    if best is None or vercmp(prov_ver, best_ver) > 0:
                                        best = cand
                                        best_ver = prov_ver
                        provider_selections[dn] = best
                resolve(provider_selections[dn])

    for target in targets:
        resolve(target)

    # Build install-scoped dep graph
    dep_graph = defaultdict(set)
    for pkg in install_set:
        for dep_str in packages[pkg].get("depends", []):
            dn = dep_name(dep_str)
            if dn in install_set:
                dep_graph[pkg].add(dn)
            elif dn in provider_selections and provider_selections[dn] in install_set:
                dep_graph[pkg].add(provider_selections[dn])

    # Kahn's with min-heap
    in_deg = {p: 0 for p in install_set}
    adj = defaultdict(list)
    for pkg in install_set:
        for d in dep_graph.get(pkg, []):
            adj[d].append(pkg)
            in_deg[pkg] += 1

    heap = sorted(p for p in install_set if in_deg[p] == 0)
    heapq.heapify(heap)
    install_order = []
    while heap:
        node = heapq.heappop(heap)
        install_order.append(node)
        for nb in adj[node]:
            in_deg[nb] -= 1
            if in_deg[nb] == 0:
                heapq.heappush(heap, nb)

    # Check version constraints
    unresolved = []
    for pkg in install_set:
        for dep_str in packages[pkg].get("depends", []):
            dn = dep_name(dep_str)
            constraint = dep_str[len(dn):]
            if not constraint:
                continue
            actual_ver = None
            if dn in install_set:
                actual_ver = packages[dn]["version"]
            elif dn in provider_selections:
                satisfier = provider_selections[dn]
                for prov in packages[satisfier].get("provides", []):
                    if dep_name(prov) == dn and "=" in prov:
                        actual_ver = prov.split("=", 1)[1]
                        break
            if actual_ver and constraint.startswith(">="):
                req_ver = constraint[2:]
                if vercmp(actual_ver, req_ver) < 0:
                    unresolved.append(f"{pkg}: {dep_str} not satisfied")

    return {
        "install_order": install_order,
        "provider_selections": dict(sorted(provider_selections.items())),
        "unresolved": unresolved,
    }


# ── SRCINFO Generation ───────────────────────────────────────────────────────

GLOBAL_FIELD_ORDER = [
    "pkgdesc", "pkgver", "pkgrel", "epoch", "url", "arch", "license",
    "makedepends", "depends", "provides", "conflicts",
    "source", "sha256sums",
]

PKG_FIELD_ORDER = ["pkgdesc", "depends", "provides", "conflicts"]


def generate_srcinfo(pkgdata):
    lines = []
    pkgbase = pkgdata["pkgbase"]
    lines.append(f"pkgbase = {pkgbase}")

    for field in GLOBAL_FIELD_ORDER:
        if field == "epoch" and not pkgdata.get("epoch"):
            continue
        val = pkgdata.get(field)
        if val is None:
            continue
        if isinstance(val, list):
            if not val:
                continue
            for item in val:
                lines.append(f"\t{field} = {item}")
        else:
            if not val:
                continue
            lines.append(f"\t{field} = {val}")

    for pkg_ov in pkgdata.get("packages", []):
        pname = pkg_ov["name"]
        lines.append("")
        lines.append(f"pkgname = {pname}")

        if pkg_ov.get("has_override", False):
            for field in PKG_FIELD_ORDER:
                val = pkg_ov.get(field)
                if val is None:
                    continue
                if isinstance(val, list):
                    if not val:
                        continue
                    for item in val:
                        lines.append(f"\t{field} = {item}")
                else:
                    lines.append(f"\t{field} = {val}")

    return "\n".join(lines) + "\n"


# ── Graphviz ─────────────────────────────────────────────────────────────────

def generate_dot(packages, providers_map, conflict_groups, dep_graph):
    lines = ['digraph deps {', '  rankdir=BT;', '  node [shape=box];']

    for pname, info in sorted(packages.items()):
        label = f"{pname}\\n{info['version']}"
        lines.append(f'  "{pname}" [label="{label}"];')

    seen_edges = set()
    for pname, deps in sorted(dep_graph.items()):
        for d in sorted(deps):
            edge = (pname, d)
            if edge not in seen_edges:
                seen_edges.add(edge)
                lines.append(f'  "{pname}" -> "{d}";')

    for a, b in conflict_groups:
        lines.append(f'  "{a}" -> "{b}" [style=dashed color=red dir=both];')

    virt_nodes = set()
    for vname, provs in sorted(providers_map.items()):
        virt_id = f"{vname}_virt"
        if virt_id not in virt_nodes:
            virt_nodes.add(virt_id)
            lines.append(
                f'  "{virt_id}" [label="{vname}" shape=ellipse '
                f'style=dashed color=blue];'
            )
        for p in sorted(provs):
            lines.append(
                f'  "{p}" -> "{virt_id}" [style=dotted color=blue];'
            )

    lines.append("}")
    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    extracted = load_extracted()
    packages = build_packages(extracted)
    providers_map = build_providers_map(packages)
    conflict_groups = find_conflict_groups(packages)
    dep_graph = build_dep_graph(packages, providers_map)
    cycles = find_cycles(dep_graph, packages)

    cyclic_nodes = set()
    for c in cycles:
        cyclic_nodes.update(c)

    build_order = topological_sort(dep_graph, packages, cyclic_nodes)

    # Vercmp comparisons
    vercmp_pairs = [
        ["1:2.5.0-1", "3.2.0-1"],
        ["14.1", "3.2.0"],
        ["2:5.0.1-1", "5.0"],
        ["1.0.0", "1.0"],
        ["3:1.0.0-1", "2:99.99-1"],
        ["1.0.0alpha", "1.0.0beta"],
        ["1.0.0", "1.0.0a"],
    ]
    vercmp_results = [[a, b, vercmp(a, b)] for a, b in vercmp_pairs]

    # Install simulation
    install_sim = simulate_install(
        ["scheduler", "webapp"], packages, providers_map
    )

    # Build report
    report = {
        "packages": {
            name: {
                "base": info["base"],
                "version": info["version"],
                "depends": info["depends"],
                "makedepends": info["makedepends"],
                "provides": info["provides"],
                "conflicts": info["conflicts"],
                "pkgdesc": info["pkgdesc"],
            }
            for name, info in sorted(packages.items())
        },
        "providers": {k: sorted(v) for k, v in sorted(providers_map.items())},
        "conflict_groups": conflict_groups,
        "circular_dependencies": cycles,
        "build_order": build_order,
        "vercmp_results": vercmp_results,
        "install_simulation": install_sim,
    }

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/report.json", "w") as f:
        json.dump(report, f, indent=2)

    # Generate SRCINFO files
    os.makedirs("/app/output/srcinfo", exist_ok=True)
    for pkgdata in extracted:
        srcinfo = generate_srcinfo(pkgdata)
        pkgbase = pkgdata["pkgbase"]
        with open(f"/app/output/srcinfo/{pkgbase}.SRCINFO", "w") as f:
            f.write(srcinfo)

    # Render dependency graph
    dot_src = generate_dot(packages, providers_map, conflict_groups, dep_graph)
    with open("/app/output/deps.dot", "w") as f:
        f.write(dot_src)
    subprocess.run(
        ["dot", "-Tsvg", "-o", "/app/output/deps.svg", "/app/output/deps.dot"],
        check=True,
    )


if __name__ == "__main__":
    main()
