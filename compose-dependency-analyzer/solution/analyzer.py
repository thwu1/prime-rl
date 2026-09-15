#!/usr/bin/env python3
"""Docker Compose Dependency Analyzer.

Statically analyzes a docker-compose.yaml to produce a comprehensive
dependency and conflict analysis report as JSON on stdout.
"""
import json
import re
import sys
from collections import defaultdict
from urllib.parse import urlparse

import yaml


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_compose(filepath):
    """Parse docker-compose.yaml and return the services dict."""
    with open(filepath) as fh:
        data = yaml.safe_load(fh)
    return data.get("services", {})


def _iter_env(env_config):
    """Yield (key, value) pairs from an environment block (dict or list)."""
    if isinstance(env_config, dict):
        for k, v in env_config.items():
            yield k, str(v)
    elif isinstance(env_config, list):
        for entry in env_config:
            entry = str(entry)
            if "=" in entry:
                k, v = entry.split("=", 1)
                yield k.strip(), v.strip()


def _extract_hostname(value):
    """Return the hostname from *value* if it looks like a URL, else None."""
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", value):
        return None
    try:
        parsed = urlparse(value)
        return parsed.hostname or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Dependency extraction
# ---------------------------------------------------------------------------

def extract_explicit_deps(services):
    """Return {service: [sorted explicit deps]} from depends_on."""
    result = {}
    for name, defn in services.items():
        depends_on = defn.get("depends_on", {})
        if isinstance(depends_on, list):
            result[name] = sorted(depends_on)
        elif isinstance(depends_on, dict):
            result[name] = sorted(depends_on.keys())
        else:
            result[name] = []
    return result


def extract_implicit_deps(services):
    """Return {service: [sorted implicit deps]} from env-var URL hostnames."""
    service_names = set(services.keys())
    result = {}
    for name, defn in services.items():
        env = defn.get("environment", {})
        deps = set()
        for _key, value in _iter_env(env):
            host = _extract_hostname(value)
            if host and host in service_names and host != name:
                deps.add(host)
        result[name] = sorted(deps)
    return result


def combine_deps(explicit, implicit):
    all_keys = sorted(set(explicit) | set(implicit))
    return {
        k: sorted(set(explicit.get(k, [])) | set(implicit.get(k, [])))
        for k in all_keys
    }


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

def detect_port_conflicts(services):
    port_to_svcs = defaultdict(list)
    for name, defn in services.items():
        for spec in defn.get("ports", []):
            parts = str(spec).split(":")
            if len(parts) == 3:
                host_port = int(parts[1])
            elif len(parts) == 2:
                host_port = int(parts[0])
            else:
                continue
            port_to_svcs[host_port].append(name)
    return sorted(
        [{"host_port": port, "services": sorted(svcs)}
         for port, svcs in port_to_svcs.items() if len(svcs) > 1],
        key=lambda c: c["host_port"],
    )


def detect_volume_conflicts(services):
    vol_to_svcs = defaultdict(list)
    for name, defn in services.items():
        for vol in defn.get("volumes", []):
            source = str(vol).split(":")[0]
            if source.startswith(".") or source.startswith("/"):
                continue  # bind mount
            vol_to_svcs[source].append(name)
    return sorted(
        [{"volume": vol, "services": sorted(svcs)}
         for vol, svcs in vol_to_svcs.items() if len(svcs) > 1],
        key=lambda c: c["volume"],
    )


def detect_nonexistent_refs(services):
    service_names = set(services.keys())
    refs = []
    for name in sorted(services):
        env = services[name].get("environment", {})
        for env_var, value in _iter_env(env):
            host = _extract_hostname(value)
            if host is None or host == name:
                continue
            if host in service_names:
                continue
            if "." in host:
                continue  # external hostname
            refs.append({
                "service": name,
                "referenced_service": host,
                "env_var": env_var,
            })
    return sorted(refs, key=lambda r: (r["service"], r["env_var"]))


# ---------------------------------------------------------------------------
# Graph algorithms
# ---------------------------------------------------------------------------

def _tarjan_sccs(graph):
    """Return list of SCCs (size > 1) via Tarjan's algorithm."""
    idx = [0]
    stack = []
    index_of = {}
    lowlink = {}
    on_stack = set()
    sccs = []

    def strongconnect(v):
        index_of[v] = lowlink[v] = idx[0]
        idx[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in graph.get(v, []):
            if w not in index_of:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], index_of[w])
        if lowlink[v] == index_of[v]:
            scc = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                scc.append(w)
                if w == v:
                    break
            if len(scc) > 1:
                sccs.append(sorted(scc))

    for v in sorted(graph):
        if v not in index_of:
            strongconnect(v)
    return sorted(sccs)


def compute_startup_waves(all_services, explicit_deps):
    """BFS-based topological sort producing parallel waves."""
    in_deg = {s: 0 for s in all_services}
    fwd = defaultdict(list)  # dep -> [dependents]
    for svc, deps in explicit_deps.items():
        for dep in deps:
            fwd[dep].append(svc)
            in_deg[svc] = in_deg.get(svc, 0) + 1

    remaining = set(all_services)
    waves = []
    while remaining:
        wave = sorted(s for s in remaining if in_deg.get(s, 0) == 0)
        if not wave:
            break  # leftover cycle
        waves.append(wave)
        for svc in wave:
            remaining.discard(svc)
            for dep in fwd.get(svc, []):
                if dep in remaining:
                    in_deg[dep] -= 1
    return waves


def compute_critical_path(all_services, explicit_deps):
    """Longest path (node count) through explicit-dep DAG + one witness."""
    waves = compute_startup_waves(all_services, explicit_deps)
    if not waves:
        return 0, []

    dist = {s: 1 for s in all_services}
    pred = {s: None for s in all_services}
    for wave in waves:
        for svc in wave:
            for dep in explicit_deps.get(svc, []):
                if dist[dep] + 1 > dist[svc]:
                    dist[svc] = dist[dep] + 1
                    pred[svc] = dep

    max_d = max(dist.values())
    end = min(s for s in all_services if dist[s] == max_d)

    path = []
    cur = end
    while cur is not None:
        path.append(cur)
        cur = pred[cur]
    path.reverse()
    return max_d, path


def compute_spof(all_services, explicit_deps):
    """Transitive impact of each service failure via reverse BFS."""
    rev = defaultdict(set)
    for svc, deps in explicit_deps.items():
        for dep in deps:
            rev[dep].add(svc)

    results = []
    for svc in all_services:
        visited = set()
        queue = list(rev.get(svc, set()))
        for s in queue:
            visited.add(s)
        while queue:
            cur = queue.pop(0)
            for nxt in rev.get(cur, set()):
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append(nxt)
        results.append({
            "service": svc,
            "affected_count": len(visited),
            "affected_services": sorted(visited),
        })
    results.sort(key=lambda r: (-r["affected_count"], r["service"]))
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def analyze(filepath):
    services = parse_compose(filepath)
    explicit = extract_explicit_deps(services)
    implicit = extract_implicit_deps(services)
    combined = combine_deps(explicit, implicit)

    svc_list = sorted(services.keys())
    return {
        "services": svc_list,
        "explicit_dependencies": {k: explicit[k] for k in svc_list},
        "implicit_dependencies": {k: implicit[k] for k in svc_list},
        "combined_dependencies": {k: combined[k] for k in svc_list},
        "port_conflicts": detect_port_conflicts(services),
        "volume_conflicts": detect_volume_conflicts(services),
        "nonexistent_references": detect_nonexistent_refs(services),
        "circular_dependencies": _tarjan_sccs(combined),
        "startup_waves": compute_startup_waves(svc_list, explicit),
        "critical_path_length": compute_critical_path(svc_list, explicit)[0],
        "critical_path": compute_critical_path(svc_list, explicit)[1],
        "single_points_of_failure": compute_spof(svc_list, explicit),
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <docker-compose.yaml>", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(analyze(sys.argv[1]), indent=2))
