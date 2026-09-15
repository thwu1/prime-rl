#!/usr/bin/env python3
"""NetworkPolicy Change-Impact Analyzer — Solution.

Evaluates baseline connectivity across 25 queries, applies 6 proposed
policy changes, and classifies each change against connectivity requirements.

"""

import copy
import json
import os
import sys

import yaml


def load_manifests(base_dir):
    """Recursively load all YAML documents from a directory tree."""
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
    """Build namespace, deployment, and policy models from raw K8s manifests."""
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
    """Return True if labels satisfy a matchLabels selector.

    An empty or None selector matches everything.
    """
    if selector is None:
        return True
    for k, v in selector.get('matchLabels', {}).items():
        if labels.get(k) != v:
            return False
    return True


def find_selecting_policies(policies, pod_labels, pod_ns, direction):
    """Return policies in pod_ns that select the pod and include direction."""
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
    """Check whether a single from/to peer entry matches.

    When both namespaceSelector and podSelector are present in the same
    entry, BOTH must match (AND semantics per K8s specification).
    """
    ns_sel = entry.get('namespaceSelector')
    pod_sel = entry.get('podSelector')
    ip_block = entry.get('ipBlock')

    # Bare entry with no selectors matches everything
    if ns_sel is None and pod_sel is None and ip_block is None:
        return True

    # ipBlock is not relevant for pod-to-pod evaluation
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
        # No namespaceSelector -> scope to the policy's own namespace
        ns_ok = (peer_ns == pol_ns)

    # Evaluate pod-label constraint
    pod_ok = selector_matches(peer_labels, pod_sel) if pod_sel is not None else True

    # AND semantics: both namespace and pod selector must match
    return ns_ok and pod_ok


def _ports_match(port_specs, port, protocol='TCP'):
    """Check whether target port/protocol matches any port spec in the rule.

    If port_specs is None (field absent from rule), all ports match.
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
        return True

    peer_field = 'from' if direction_key == 'ingress' else 'to'

    for pol in selecting:
        for rule in pol.get(direction_key, []):
            peers = rule.get(peer_field)
            # None means all ports match; do not default to []
            rule_ports = rule.get('ports')

            if not _ports_match(rule_ports, port, proto):
                continue

            if peers is None:
                # No from/to -> matches all peers on matched ports
                return True

            for entry in peers:
                if _peer_entry_matches(entry, peer_labels, peer_ns,
                                       pol['namespace'], all_ns):
                    return True

    return False


def evaluate_query(query, namespaces, deployments, policies):
    """Evaluate a single connectivity query; returns 'ALLOWED' or 'DENIED'."""
    src = deployments.get(query['source'])
    dst = deployments.get(query['destination'])
    if src is None or dst is None:
        return 'DENIED'

    port = query['port']
    proto = query.get('protocol', 'TCP')

    # Egress check at the source pod
    eg_pols = find_selecting_policies(
        policies, src['labels'], src['namespace'], 'Egress')
    if not _evaluate_direction(eg_pols, 'egress',
                               dst['labels'], dst['namespace'],
                               port, proto, namespaces):
        return 'DENIED'

    # Ingress check at the destination pod
    ig_pols = find_selecting_policies(
        policies, dst['labels'], dst['namespace'], 'Ingress')
    if not _evaluate_direction(ig_pols, 'ingress',
                               src['labels'], src['namespace'],
                               port, proto, namespaces):
        return 'DENIED'

    return 'ALLOWED'


def compute_all_verdicts(queries, namespaces, deployments, policies):
    """Compute verdicts for all queries."""
    results = {}
    for qid in sorted(queries):
        results[qid] = evaluate_query(queries[qid], namespaces, deployments, policies)
    return results


def policy_from_manifest(manifest):
    """Convert a raw K8s NetworkPolicy manifest dict to our internal model."""
    meta = manifest.get('metadata', {})
    spec = manifest.get('spec', {})
    return {
        'name': meta.get('name', ''),
        'namespace': meta.get('namespace', ''),
        'podSelector': spec.get('podSelector', {}),
        'policyTypes': spec.get('policyTypes', []),
        'ingress': spec.get('ingress') or [],
        'egress': spec.get('egress') or [],
    }


def apply_change(policies, change):
    """Apply a proposed change to a copy of the policy list."""
    action = change['action']
    modified = copy.deepcopy(policies)

    if action == 'replace':
        target = change['target_policy']
        target_ns = change['target_namespace']
        replacement = policy_from_manifest(change['policy'])
        for i, pol in enumerate(modified):
            if pol['name'] == target and pol['namespace'] == target_ns:
                modified[i] = replacement
                break
        return modified

    elif action == 'add':
        addition = policy_from_manifest(change['policy'])
        modified.append(addition)
        return modified

    elif action == 'delete':
        target = change['target_policy']
        target_ns = change['target_namespace']
        return [p for p in modified
                if not (p['name'] == target and p['namespace'] == target_ns)]

    elif action == 'replace_multiple':
        for mod in change['modifications']:
            target = mod['target_policy']
            target_ns = mod['target_namespace']
            replacement = policy_from_manifest(mod['policy'])
            for i, pol in enumerate(modified):
                if pol['name'] == target and pol['namespace'] == target_ns:
                    modified[i] = replacement
                    break
        return modified

    return modified


def classify_change(baseline, modified_verdicts, requirements):
    """Classify a change based on its impact on required/forbidden connections."""
    required = set(requirements.get('required', {}).keys())
    forbidden = set(requirements.get('forbidden', {}).keys())

    newly_allowed = []
    newly_denied = []

    for qid in sorted(baseline.keys()):
        if baseline[qid] == 'DENIED' and modified_verdicts[qid] == 'ALLOWED':
            newly_allowed.append(qid)
        elif baseline[qid] == 'ALLOWED' and modified_verdicts[qid] == 'DENIED':
            newly_denied.append(qid)

    breaks_required = any(qid in required for qid in newly_denied)
    opens_forbidden = any(qid in forbidden for qid in newly_allowed)

    if breaks_required and opens_forbidden:
        classification = 'CRITICAL'
    elif breaks_required:
        classification = 'BREAKS_REQUIRED'
    elif opens_forbidden:
        classification = 'OPENS_FORBIDDEN'
    else:
        classification = 'SAFE'

    return {
        'classification': classification,
        'newly_allowed': newly_allowed,
        'newly_denied': newly_denied,
    }


def load_proposed_changes(changes_dir):
    """Load proposed change YAML files from a directory."""
    changes = {}
    for fn in sorted(os.listdir(changes_dir)):
        if not fn.endswith(('.yaml', '.yml')):
            continue
        change_id = os.path.splitext(fn)[0]
        with open(os.path.join(changes_dir, fn)) as f:
            changes[change_id] = yaml.safe_load(f)
    return changes


def main():
    manifest_dir = '/app/manifests'
    query_file = '/app/queries.json'
    requirements_file = '/app/connectivity_requirements.json'
    changes_dir = '/app/proposed_changes'
    output_file = '/app/impact_report.json'

    # Load and parse manifests
    docs = load_manifests(manifest_dir)
    ns_map, deploy_map, pol_list = extract_model(docs)

    # Load queries and requirements
    with open(query_file) as f:
        queries = json.load(f)
    with open(requirements_file) as f:
        requirements = json.load(f)

    # Compute baseline verdicts
    baseline = compute_all_verdicts(queries, ns_map, deploy_map, pol_list)

    # Process each proposed change
    changes = load_proposed_changes(changes_dir)
    change_results = {}
    for change_id in sorted(changes):
        change = changes[change_id]
        modified_policies = apply_change(pol_list, change)
        modified_verdicts = compute_all_verdicts(
            queries, ns_map, deploy_map, modified_policies)
        change_results[change_id] = classify_change(
            baseline, modified_verdicts, requirements)

    # Write report
    report = {
        'baseline': baseline,
        'changes': change_results,
    }
    with open(output_file, 'w') as f:
        json.dump(report, f, indent=2)

    print(f'Impact report written to {output_file}')
    print(f'Baseline: {sum(1 for v in baseline.values() if v == "ALLOWED")} ALLOWED, '
          f'{sum(1 for v in baseline.values() if v == "DENIED")} DENIED')
    for cid, result in sorted(change_results.items()):
        print(f'  {cid}: {result["classification"]} '
              f'(+{len(result["newly_allowed"])} allowed, '
              f'-{len(result["newly_denied"])} denied)')


if __name__ == '__main__':
    main()
