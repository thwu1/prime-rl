#!/usr/bin/env python3
"""Docker Compose Production Topology Auditor.

Merges base and production overlay compose files following Docker Compose v2
file-merge semantics, applies env-var substitution, identifies infrastructure
misconfigurations, and performs dependency topology analysis.
"""
import copy
import json
import os
import re
from collections import defaultdict
from urllib.parse import urlparse

import yaml


# ---------------------------------------------------------------------------
# .env file parsing
# ---------------------------------------------------------------------------

def parse_env_file(filepath):
    """Parse a Docker Compose .env file into a dict."""
    env = {}
    if not os.path.exists(filepath):
        return env
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, value = line.split('=', 1)
                env[key.strip()] = value.strip()
    return env


# ---------------------------------------------------------------------------
# Environment variable substitution
# ---------------------------------------------------------------------------

def substitute_vars(value, env):
    """Substitute ${VAR}, ${VAR:-default}, ${VAR-default} patterns."""
    def replacer(match):
        expr = match.group(1)
        if ':-' in expr:
            var, default = expr.split(':-', 1)
            v = env.get(var, '')
            return v if v else default
        elif ':?' in expr:
            var, _ = expr.split(':?', 1)
            return env.get(var, '')
        elif '-' in expr:
            var, default = expr.split('-', 1)
            return env.get(var, default)
        elif '?' in expr:
            var, _ = expr.split('?', 1)
            return env.get(var, '')
        return env.get(expr, '')

    return re.sub(r'\$\{([^}]+)\}', replacer, str(value))


def substitute_recursive(obj, env):
    """Recursively substitute env vars in all string values."""
    if isinstance(obj, str):
        return substitute_vars(obj, env)
    if isinstance(obj, dict):
        return {k: substitute_recursive(v, env) for k, v in obj.items()}
    if isinstance(obj, list):
        return [substitute_recursive(item, env) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# Docker Compose v2 merge logic
# ---------------------------------------------------------------------------

CONCAT_KEYS = frozenset({
    'ports', 'expose', 'volumes', 'dns', 'dns_search', 'tmpfs',
    'extra_hosts', 'cap_add', 'cap_drop', 'security_opt',
    'device_cgroup_rules', 'configs', 'secrets',
})

MAPPING_KEYS = frozenset({
    'environment', 'labels', 'build', 'deploy', 'healthcheck',
    'logging', 'ulimits', 'annotations', 'sysctls',
})


def deep_merge(base, override):
    """Deep merge two dicts. Override values win for same keys."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def normalize_networks(nets):
    """Normalize service-level networks to mapping form."""
    if nets is None:
        return {}
    if isinstance(nets, list):
        return {n: None for n in nets}
    return dict(nets)


def normalize_depends_on(deps):
    """Normalize depends_on to mapping form."""
    if deps is None:
        return {}
    if isinstance(deps, list):
        return {d: {'condition': 'service_started'} for d in deps}
    return dict(deps)


def merge_service(base_svc, override_svc):
    """Merge two service configs following Docker Compose v2 semantics."""
    result = copy.deepcopy(base_svc)
    for key, value in override_svc.items():
        if key in CONCAT_KEYS:
            result[key] = result.get(key, []) + copy.deepcopy(value)
        elif key == 'depends_on':
            base_deps = normalize_depends_on(result.get(key))
            override_deps = normalize_depends_on(value)
            result[key] = deep_merge(base_deps, override_deps)
        elif key == 'networks':
            base_nets = normalize_networks(result.get(key))
            override_nets = normalize_networks(value)
            merged = {**base_nets, **override_nets}
            result[key] = merged
        elif key in MAPPING_KEYS:
            if isinstance(result.get(key), dict) and isinstance(value, dict):
                result[key] = deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def merge_compose_files(base, override):
    """Merge two parsed compose file dicts."""
    result = copy.deepcopy(base)
    for svc_name, svc_config in override.get('services', {}).items():
        if svc_name in result.get('services', {}):
            result['services'][svc_name] = merge_service(
                result['services'][svc_name], svc_config)
        else:
            result['services'][svc_name] = copy.deepcopy(svc_config)
    for top_key in ['networks', 'volumes']:
        if top_key in override:
            result[top_key] = deep_merge(
                result.get(top_key, {}), override[top_key])
    return result


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

def get_service_networks(svc_config):
    """Return sorted list of networks a service is connected to."""
    nets = svc_config.get('networks')
    if nets is None:
        return ['default']
    if isinstance(nets, list):
        return sorted(nets)
    if isinstance(nets, dict):
        return sorted(nets.keys())
    return ['default']


def extract_hostname(value):
    """Extract hostname from a URL-like string. None if not a URL."""
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9+.\-]*://', str(value)):
        return None
    try:
        parsed = urlparse(str(value))
        return parsed.hostname or None
    except Exception:
        return None


def iter_env_items(env_section):
    """Yield (key, value) pairs from an environment section."""
    if isinstance(env_section, dict):
        for k, v in env_section.items():
            yield k, str(v) if v is not None else ''
    elif isinstance(env_section, list):
        for entry in env_section:
            entry = str(entry)
            if '=' in entry:
                k, v = entry.split('=', 1)
                yield k.strip(), v.strip()


def parse_memory(value):
    """Parse Docker memory notation (e.g. 512M, 1G) to bytes."""
    s = str(value).strip().lower()
    multipliers = {'b': 1, 'k': 1024, 'm': 1024**2, 'g': 1024**3}
    if s and s[-1] in multipliers:
        return float(s[:-1]) * multipliers[s[-1]]
    try:
        return float(s)
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# Dependency extraction
# ---------------------------------------------------------------------------

def extract_explicit_deps(services):
    """Return {service: [sorted explicit deps]} from depends_on."""
    result = {}
    for name, defn in services.items():
        depends_on = defn.get('depends_on', {})
        if isinstance(depends_on, list):
            result[name] = sorted(depends_on)
        elif isinstance(depends_on, dict):
            result[name] = sorted(depends_on.keys())
        else:
            result[name] = []
    return result


def extract_implicit_deps(services, service_names):
    """Return {service: [sorted implicit deps]} from env-var URL hostnames."""
    svc_set = set(service_names)
    result = {}
    for name in service_names:
        env = services[name].get('environment', {})
        deps = set()
        for _key, value in iter_env_items(env):
            host = extract_hostname(value)
            if host and host in svc_set and host != name and '.' not in host:
                deps.add(host)
        result[name] = sorted(deps)
    return result


def build_combined_deps(explicit, implicit, service_names):
    """Return {service: [sorted combined deps]}."""
    return {
        s: sorted(set(explicit.get(s, [])) | set(implicit.get(s, [])))
        for s in service_names
    }


# ---------------------------------------------------------------------------
# Graph algorithms
# ---------------------------------------------------------------------------

def tarjan_sccs(graph):
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


def compute_startup_waves(service_names, explicit_deps):
    """BFS-based topological sort producing parallel startup waves."""
    in_deg = {s: 0 for s in service_names}
    fwd = defaultdict(list)
    for svc, deps in explicit_deps.items():
        for dep in deps:
            if dep in in_deg:
                fwd[dep].append(svc)
                in_deg[svc] = in_deg.get(svc, 0) + 1

    remaining = set(service_names)
    waves = []
    while remaining:
        wave = sorted(s for s in remaining if in_deg.get(s, 0) == 0)
        if not wave:
            break
        waves.append(wave)
        for svc in wave:
            remaining.discard(svc)
            for dep in fwd.get(svc, []):
                if dep in remaining:
                    in_deg[dep] -= 1
    return waves


def compute_critical_path(service_names, explicit_deps):
    """Longest path (node count) through explicit-dep DAG + one witness."""
    waves = compute_startup_waves(service_names, explicit_deps)
    if not waves:
        return 0, []

    dist = {s: 1 for s in service_names}
    pred = {s: None for s in service_names}
    for wave in waves:
        for svc in wave:
            for dep in sorted(explicit_deps.get(svc, [])):
                if dist[dep] + 1 > dist[svc]:
                    dist[svc] = dist[dep] + 1
                    pred[svc] = dep

    max_d = max(dist.values())
    end = min(s for s in service_names if dist[s] == max_d)

    path = []
    cur = end
    while cur is not None:
        path.append(cur)
        cur = pred[cur]
    path.reverse()
    return max_d, path


def compute_spof(service_names, explicit_deps):
    """Transitive impact of each service failure via reverse BFS."""
    rev = defaultdict(set)
    for svc, deps in explicit_deps.items():
        for dep in deps:
            rev[dep].add(svc)

    results = []
    for svc in service_names:
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
            'service': svc,
            'affected_count': len(visited),
            'affected_services': sorted(visited),
        })
    results.sort(key=lambda r: (-r['affected_count'], r['service']))
    return results


# ---------------------------------------------------------------------------
# Main audit
# ---------------------------------------------------------------------------

def audit(compose_dir='/app'):
    # Parse compose files
    with open(os.path.join(compose_dir, 'docker-compose.yml')) as f:
        base = yaml.safe_load(f)
    with open(os.path.join(compose_dir, 'docker-compose.prod.yml')) as f:
        override = yaml.safe_load(f)

    # Parse and merge env files (prod overrides base)
    env = parse_env_file(os.path.join(compose_dir, '.env'))
    env_prod = parse_env_file(os.path.join(compose_dir, '.env.prod'))
    env.update(env_prod)

    # Merge compose files
    merged = merge_compose_files(base, override)
    services = merged.get('services', {})
    service_names = sorted(services.keys())

    # Substitute env vars throughout
    services = substitute_recursive(services, env)

    # Build per-service network map
    svc_networks = {}
    for name in service_names:
        svc_networks[name] = get_service_networks(services[name])

    # --- Network violations ---
    network_violations = []
    for name in service_names:
        for env_var, value in iter_env_items(services[name].get('environment', {})):
            hostname = extract_hostname(value)
            if hostname is None or hostname == name:
                continue
            if '.' in hostname:
                continue
            if hostname not in service_names:
                continue
            source_nets = set(svc_networks[name])
            target_nets = set(svc_networks[hostname])
            if not source_nets & target_nets:
                network_violations.append({
                    'source': name,
                    'target': hostname,
                    'env_var': env_var,
                    'source_networks': sorted(source_nets),
                    'target_networks': sorted(target_nets),
                })
    network_violations.sort(key=lambda x: (x['source'], x['target'], x['env_var']))

    # --- Port conflicts ---
    port_map = defaultdict(list)
    for name in service_names:
        for port_spec in services[name].get('ports', []):
            parts = str(port_spec).split(':')
            if len(parts) == 2:
                host_port = int(parts[0])
            elif len(parts) == 3:
                host_port = int(parts[1])
            else:
                continue
            port_map[host_port].append(name)
    port_conflicts = []
    for port in sorted(port_map):
        svcs = sorted(set(port_map[port]))
        if len(svcs) > 1:
            port_conflicts.append({
                'host_port': port,
                'services': svcs,
            })

    # --- Resource violations ---
    resource_violations = []
    for name in service_names:
        deploy = services[name].get('deploy', {})
        resources = deploy.get('resources', {})
        limits = resources.get('limits', {})
        reservations = resources.get('reservations', {})
        limit_mem = limits.get('memory')
        reserve_mem = reservations.get('memory')
        if limit_mem and reserve_mem:
            if parse_memory(reserve_mem) > parse_memory(limit_mem):
                resource_violations.append({
                    'service': name,
                    'limit': str(limit_mem),
                    'reservation': str(reserve_mem),
                })
    resource_violations.sort(key=lambda x: x['service'])

    # --- Healthcheck gaps ---
    healthcheck_gaps = []
    for name in service_names:
        depends_on = services[name].get('depends_on', {})
        if isinstance(depends_on, list):
            depends_on = {d: {'condition': 'service_started'} for d in depends_on}
        for dep_name, dep_config in depends_on.items():
            if isinstance(dep_config, dict):
                condition = dep_config.get('condition', 'service_started')
            else:
                condition = 'service_started'
            if condition == 'service_healthy':
                dep_svc = services.get(dep_name, {})
                if 'healthcheck' not in dep_svc:
                    healthcheck_gaps.append({
                        'service': name,
                        'depends_on': dep_name,
                        'condition': condition,
                    })
    healthcheck_gaps.sort(key=lambda x: (x['service'], x['depends_on']))

    # --- Undefined references ---
    undefined_refs = []
    for name in service_names:
        for env_var, value in iter_env_items(services[name].get('environment', {})):
            hostname = extract_hostname(value)
            if hostname is None or hostname == name:
                continue
            if '.' in hostname:
                continue
            if hostname in service_names:
                continue
            undefined_refs.append({
                'service': name,
                'env_var': env_var,
                'referenced_hostname': hostname,
            })
    undefined_refs.sort(key=lambda x: (x['service'], x['env_var']))

    # --- Dependency topology analysis ---
    explicit_deps = extract_explicit_deps(services)
    implicit_deps = extract_implicit_deps(services, service_names)
    combined_deps = build_combined_deps(explicit_deps, implicit_deps, service_names)

    circular_deps = tarjan_sccs(combined_deps)
    startup_waves = compute_startup_waves(service_names, explicit_deps)
    crit_len, crit_path = compute_critical_path(service_names, explicit_deps)
    spof = compute_spof(service_names, explicit_deps)

    return {
        'services': service_names,
        'network_violations': network_violations,
        'port_conflicts': port_conflicts,
        'resource_violations': resource_violations,
        'healthcheck_gaps': healthcheck_gaps,
        'undefined_references': undefined_refs,
        'circular_dependencies': circular_deps,
        'startup_waves': startup_waves,
        'critical_path_length': crit_len,
        'critical_path': crit_path,
        'single_points_of_failure': spof,
    }


if __name__ == '__main__':
    print(json.dumps(audit(), indent=2))
