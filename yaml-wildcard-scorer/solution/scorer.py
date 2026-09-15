#!/usr/bin/env python3
"""Kubernetes configuration drift analyzer.

Compares Kustomize-rendered desired state against live cluster state
using the KV-wildcard IoU metric with Kubernetes semantic extensions.
"""

import json
import os
import subprocess

import yaml


def read_audit_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def render_kustomize(overlay_dir):
    result = subprocess.run(
        ["kustomize", "build", overlay_dir],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def preprocess_wildcards(raw_text):
    """Detect wildcard annotations (# *) and append * to the key name."""
    output_lines = []
    for line in raw_text.splitlines():
        if '#' in line and line.rstrip().endswith('*'):
            parts = line.split(':', 1)
            if len(parts) == 2:
                output_lines.append(parts[0].rstrip() + '*:' + parts[1])
            else:
                output_lines.append(line)
        else:
            output_lines.append(line)
    if raw_text.endswith('\n'):
        output_lines.append('')
    return '\n'.join(output_lines)


def parse_multi_doc(text):
    """Parse a multi-document YAML string into a list of dicts."""
    docs = []
    for doc in yaml.safe_load_all(text):
        if doc is not None:
            docs.append(doc)
    return docs


def resource_identity(doc):
    """Extract resource identity as apiVersion/kind/name."""
    api_version = doc.get('apiVersion', '')
    kind = doc.get('kind', '')
    meta = doc.get('metadata', {})
    name = meta.get('name', '')
    return f"{api_version}/{kind}/{name}"


def get_leaf_nodes(d):
    """Recursively extract leaf key-value pairs from a YAML dict.

    For sequences of mappings, each mapping is flattened independently
    under the enclosing key -- no sequence indices in key paths.
    """
    leaf_nodes = []
    if not isinstance(d, dict):
        return leaf_nodes
    for key, value in d.items():
        clean_key = key.rstrip('*')
        is_wc = key.endswith('*')
        if isinstance(value, dict):
            sub_leaves = get_leaf_nodes(value)
            for leaf in sub_leaves:
                leaf_nodes.append({
                    'key_path': [clean_key] + leaf['key_path'],
                    'value': leaf['value'],
                    'wildcard': leaf['wildcard'],
                })
        elif isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
            for item in value:
                sub_leaves = get_leaf_nodes(item)
                for leaf in sub_leaves:
                    leaf_nodes.append({
                        'key_path': [clean_key] + leaf['key_path'],
                        'value': leaf['value'],
                        'wildcard': leaf['wildcard'],
                    })
        else:
            leaf_nodes.append({
                'key_path': [clean_key],
                'value': value,
                'wildcard': is_wc,
            })
    return leaf_nodes


def is_resource_quantity_path(key_path):
    """Check whether a key path corresponds to a K8s resource quantity field.

    Matches paths containing [..., 'resources', 'requests'|'limits', <field>].
    """
    for i in range(len(key_path) - 2):
        if key_path[i] == 'resources' and key_path[i + 1] in ('requests', 'limits'):
            return True
    return False


def parse_k8s_quantity(value):
    """Parse a Kubernetes resource quantity to a numeric value.

    Handles:
      - int/float values (already in base units)
      - String suffixes: Ki, Mi, Gi (memory -> bytes), m (cpu -> cores)
      - Plain numeric strings
    """
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith('Gi'):
        try:
            return float(s[:-2]) * 1073741824
        except ValueError:
            return None
    if s.endswith('Mi'):
        try:
            return float(s[:-2]) * 1048576
        except ValueError:
            return None
    if s.endswith('Ki'):
        try:
            return float(s[:-2]) * 1024
        except ValueError:
            return None
    if s.endswith('m'):
        try:
            return float(s[:-1]) / 1000.0
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def apply_protocol_defaults(doc):
    """Inject protocol: TCP into container port objects that lack it."""
    spec = doc.get('spec', {})
    template = spec.get('template', {})
    template_spec = template.get('spec', {})
    containers = template_spec.get('containers', [])
    if not isinstance(containers, list):
        return
    for container in containers:
        if not isinstance(container, dict):
            continue
        ports = container.get('ports', [])
        if not isinstance(ports, list):
            continue
        for port in ports:
            if isinstance(port, dict) and 'protocol' not in port:
                port['protocol'] = 'TCP'


def values_equal(ref_leaf, cand_leaf):
    """Compare two leaf values, applying K8s quantity normalization if applicable."""
    if is_resource_quantity_path(ref_leaf['key_path']):
        ref_qty = parse_k8s_quantity(ref_leaf['value'])
        cand_qty = parse_k8s_quantity(cand_leaf['value'])
        if ref_qty is not None and cand_qty is not None:
            return abs(ref_qty - cand_qty) < 1e-9
    return ref_leaf['value'] == cand_leaf['value']


def calc_intersection(ref_leaves, cand_leaves):
    """Count intersection: for each ref leaf, find a matching candidate leaf."""
    intersection = 0
    for ref_leaf in ref_leaves:
        for cand_leaf in cand_leaves:
            if cand_leaf['key_path'] == ref_leaf['key_path']:
                if ref_leaf['wildcard'] or values_equal(ref_leaf, cand_leaf):
                    intersection += 1
                    break
    return intersection


def compute_iou(ref_leaves, cand_leaves):
    """Compute IoU similarity score."""
    intersection = calc_intersection(ref_leaves, cand_leaves)
    union = len(ref_leaves) + len(cand_leaves) - intersection
    if union == 0:
        return 0.0
    return intersection / union


def main():
    config = read_audit_config('/app/audit.yaml')

    results = {
        'environments': {},
        'aggregate_mean': 0.0,
    }
    all_resource_scores = []

    for env_name, env_config in sorted(config['environments'].items()):
        # Render desired state via kustomize
        desired_yaml = render_kustomize(env_config['overlay'])
        desired_docs = parse_multi_doc(desired_yaml)

        # Read live state
        with open(env_config['live']) as f:
            raw_live = f.read()

        # Parse raw live state for identity extraction
        raw_live_docs = parse_multi_doc(raw_live)

        # Parse wildcard-preprocessed live state for leaf extraction
        annotated_live = preprocess_wildcards(raw_live)
        annotated_live_docs = parse_multi_doc(annotated_live)

        # Apply protocol defaults to all documents
        for doc in desired_docs:
            apply_protocol_defaults(doc)
        for doc in annotated_live_docs:
            apply_protocol_defaults(doc)

        # Index desired docs by identity
        desired_by_id = {}
        for doc in desired_docs:
            rid = resource_identity(doc)
            desired_by_id[rid] = doc

        # Score each live resource
        env_scores = {}
        for i, raw_doc in enumerate(raw_live_docs):
            rid = resource_identity(raw_doc)
            annotated_doc = annotated_live_docs[i]

            if rid in desired_by_id:
                ref_leaves = get_leaf_nodes(annotated_doc)
                cand_leaves = get_leaf_nodes(desired_by_id[rid])
                score = compute_iou(ref_leaves, cand_leaves)
            else:
                score = 0.0

            env_scores[rid] = score
            all_resource_scores.append(score)

        env_mean = sum(env_scores.values()) / len(env_scores) if env_scores else 0.0
        results['environments'][env_name] = {
            'resources': env_scores,
            'mean': env_mean,
        }

    if all_resource_scores:
        results['aggregate_mean'] = sum(all_resource_scores) / len(all_resource_scores)

    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/drift_report.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Drift report written to /app/output/drift_report.json")
    print(f"Aggregate mean: {results['aggregate_mean']:.6f}")


if __name__ == '__main__':
    main()
