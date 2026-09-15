#!/usr/bin/env python3
"""Kubernetes NetworkPolicy Connectivity Analyzer — corrected version.

Fixes three semantic bugs in the original analyzer:
1. AND vs OR: combined namespaceSelector+podSelector requires both to match
2. Default behavior: no selecting policy means traffic is allowed (not denied)
3. Port wildcard: absent ports field means all ports match (not none)

"""

import json
import os
import sys

import yaml


def load_manifests(base_dir):
    """Recursively load all YAML documents from a directory."""
    docs = []
    for dirpath, _, filenames in os.walk(base_dir):
        for fn in sorted(filenames):
            if not fn.endswith(('.yaml', '.yml')):
                continue
            path = os.path.join(dirpath, fn)
            with open(path) as fh:
                for doc in yaml.safe_load_all(fh):
                    if doc is not None:
                        docs.append(doc)
    return docs


def extract_model(docs):
    """Build namespace, deployment, and policy models from raw manifests."""
    namespaces = {}
    deployments = {}
    net_policies = []

    for doc in docs:
        kind = doc.get('kind', '')
        meta = doc.get('metadata', {})
        name = meta.get('name', '')
        ns = meta.get('namespace', '')

        if kind == 'Namespace':
            namespaces[name] = {
                'name': name,
                'labels': meta.get('labels', {}),
            }
        elif kind == 'Deployment':
            tpl = doc.get('spec', {}).get('template', {})
            pod_labels = tpl.get('metadata', {}).get('labels', {})
            ports = []
            for ctr in tpl.get('spec', {}).get('containers', []):
                for p in ctr.get('ports', []):
                    ports.append(p.get('containerPort'))
            deployments[f'{ns}/{name}'] = {
                'name': name,
                'namespace': ns,
                'labels': pod_labels,
                'ports': ports,
            }
        elif kind == 'NetworkPolicy':
            spec = doc.get('spec', {})
            net_policies.append({
                'name': name,
                'namespace': ns,
                'podSelector': spec.get('podSelector', {}),
                'policyTypes': spec.get('policyTypes', []),
                'ingress': spec.get('ingress') or [],
                'egress': spec.get('egress') or [],
            })

    return namespaces, deployments, net_policies


def selector_matches(labels, selector):
    """Return True if `labels` satisfy the given label selector."""
    for k, v in selector.get('matchLabels', {}).items():
        if labels.get(k) != v:
            return False
    return True


def find_selecting_policies(policies, pod_labels, pod_ns, direction):
    """Return policies in `pod_ns` that select the pod and include `direction`."""
    selected = []
    for pol in policies:
        if pol['namespace'] != pod_ns:
            continue
        if direction not in pol['policyTypes']:
            continue
        if selector_matches(pod_labels, pol['podSelector']):
            selected.append(pol)
    return selected


def _peer_entry_matches(entry, peer_labels, peer_ns, pol_ns, all_ns):
    """Determine whether a single from/to peer entry matches.

    When both namespaceSelector and podSelector are present in the same
    entry, BOTH must match (AND semantics per K8s specification).
    """
    ns_sel = entry.get('namespaceSelector')
    pod_sel = entry.get('podSelector')
    ip_block = entry.get('ipBlock')

    if ns_sel is None and pod_sel is None and ip_block is None:
        return True

    if ip_block is not None:
        return False

    # Evaluate namespace constraint
    if ns_sel is not None:
        ns_ok = any(
            selector_matches(info['labels'], ns_sel)
            for ns_name, info in all_ns.items()
            if ns_name == peer_ns
        )
    else:
        ns_ok = (peer_ns == pol_ns)

    # Evaluate pod-label constraint
    pod_ok = selector_matches(peer_labels, pod_sel) if pod_sel is not None else True

    # FIX 1: AND semantics — both namespace and pod selector must match
    return ns_ok and pod_ok


def _ports_match(port_specs, port, protocol='TCP'):
    """Check whether target port/protocol matches any port spec in the rule.

    If port_specs is None (field absent), all ports are matched.
    """
    if port_specs is None:
        return True
    for spec in port_specs:
        if spec.get('port') == port and spec.get('protocol', 'TCP') == protocol:
            return True
    return False


def _evaluate_direction(selecting, direction_key, peer_labels, peer_ns,
                        port, proto, all_ns):
    """Check whether traffic is allowed for one direction (ingress/egress).

    If no policy of this type selects the pod, all traffic is allowed
    (Kubernetes default behavior).
    """
    if not selecting:
        # FIX 2: default allow when no policy of this type selects the pod
        return True

    peer_field = 'from' if direction_key == 'ingress' else 'to'

    for pol in selecting:
        for rule in pol.get(direction_key, []):
            peers = rule.get(peer_field)
            # FIX 3: None means all ports match; do not default to []
            rule_ports = rule.get('ports')

            if not _ports_match(rule_ports, port, proto):
                continue

            if peers is None:
                return True

            for entry in peers:
                if _peer_entry_matches(entry, peer_labels, peer_ns,
                                       pol['namespace'], all_ns):
                    return True

    return False


def evaluate(query, namespaces, deployments, policies):
    """Evaluate a single connectivity query; returns 'ALLOWED' or 'DENIED'."""
    src = deployments.get(query['source'])
    dst = deployments.get(query['destination'])
    if src is None or dst is None:
        return 'DENIED'

    port = query['port']
    proto = query.get('protocol', 'TCP')

    eg_pols = find_selecting_policies(
        policies, src['labels'], src['namespace'], 'Egress')
    if not _evaluate_direction(eg_pols, 'egress',
                               dst['labels'], dst['namespace'],
                               port, proto, namespaces):
        return 'DENIED'

    ig_pols = find_selecting_policies(
        policies, dst['labels'], dst['namespace'], 'Ingress')
    if not _evaluate_direction(ig_pols, 'ingress',
                               src['labels'], src['namespace'],
                               port, proto, namespaces):
        return 'DENIED'

    return 'ALLOWED'


def main():
    manifest_dir = '/app/manifests'
    query_file = '/app/queries.json'
    output_file = '/app/results.json'

    docs = load_manifests(manifest_dir)
    ns_map, deploy_map, pol_list = extract_model(docs)

    with open(query_file) as f:
        queries = json.load(f)

    results = {}
    for qid in sorted(queries):
        results[qid] = {'verdict': evaluate(queries[qid], ns_map, deploy_map, pol_list)}

    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f'Evaluated {len(results)} queries -> {output_file}')


if __name__ == '__main__':
    main()
