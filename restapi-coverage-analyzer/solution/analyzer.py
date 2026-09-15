#!/usr/bin/env python3

"""REST API Competition Analyzer.

Integrates OpenAPI spec, HTTP traffic captures, and JaCoCo coverage reports
to produce a comprehensive ranked evaluation with graph visualization.
"""

import json
import os
import re
import glob
import math
import subprocess
import yaml
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
from pathlib import Path


def resolve_ref(spec, ref_str):
    """Resolve a $ref string to the referenced object."""
    parts = ref_str.lstrip('#/').split('/')
    obj = spec
    for p in parts:
        obj = obj[p]
    return obj


def resolve_schema(spec, schema):
    """Recursively resolve a schema, handling $ref and allOf composition."""
    if schema is None:
        return {}

    if '$ref' in schema:
        resolved = resolve_ref(spec, schema['$ref'])
        return resolve_schema(spec, resolved)

    if 'allOf' in schema:
        merged = {'type': 'object', 'properties': {}}
        for sub in schema['allOf']:
            resolved_sub = resolve_schema(spec, sub)
            if 'properties' in resolved_sub:
                merged['properties'].update(resolved_sub['properties'])
        return merged

    return schema


def get_response_properties(spec, operation):
    """Extract top-level response properties (name -> type) from 2xx responses."""
    properties = {}
    responses = operation.get('responses', {})
    for status_code, response in responses.items():
        code = str(status_code)
        if code.startswith('2'):
            content = response.get('content', {})
            for media_type, media_obj in content.items():
                schema = media_obj.get('schema', {})
                resolved = resolve_schema(spec, schema)
                if resolved.get('type') == 'object' and 'properties' in resolved:
                    for prop_name, prop_schema in resolved['properties'].items():
                        prop_resolved = resolve_schema(spec, prop_schema)
                        properties[prop_name] = prop_resolved.get('type', 'string')
    return properties


def get_request_params(spec, operation, path_item_params=None):
    """Extract request parameter names and types from path, query, and body."""
    params = {}

    # Path-level and operation-level parameters
    all_params = list(path_item_params or []) + list(operation.get('parameters', []))
    for param in all_params:
        if '$ref' in param:
            resolved_param = resolve_ref(spec, param['$ref'])
        else:
            resolved_param = param
        name = resolved_param.get('name')
        param_schema = resolved_param.get('schema', {})
        param_resolved = resolve_schema(spec, param_schema)
        param_type = param_resolved.get('type', 'string')
        if name:
            params[name] = param_type

    # Request body properties
    body = operation.get('requestBody', {})
    if '$ref' in body:
        body = resolve_ref(spec, body['$ref'])
    content = body.get('content', {})
    for media_type, media_obj in content.items():
        schema = media_obj.get('schema', {})
        resolved = resolve_schema(spec, schema)
        if resolved.get('type') == 'object' and 'properties' in resolved:
            for prop_name, prop_schema in resolved['properties'].items():
                prop_resolved = resolve_schema(spec, prop_schema)
                params[prop_name] = prop_resolved.get('type', 'string')

    return params


def extract_operations(spec):
    """Extract all operations from the OpenAPI spec paths."""
    operations = []
    for path, path_item in spec.get('paths', {}).items():
        path_item_params = path_item.get('parameters', [])
        for method in ['get', 'post', 'put', 'delete', 'patch']:
            if method in path_item:
                op = path_item[method]
                op_id = op.get('operationId', f'{method}_{path}')
                operations.append({
                    'operationId': op_id,
                    'method': method.upper(),
                    'path': path,
                    'operation': op,
                    'path_item_params': path_item_params,
                })
    return operations


def path_template_to_regex(template):
    """Convert an OpenAPI path template to a regex."""
    pattern = re.sub(r'\{[^}]+\}', '([^/]+)', template)
    return f'^{pattern}$'


def match_traffic_to_operations(traffic_entries, operations, server_base_path):
    """Match each traffic log entry to a spec operation via method + path template."""
    matches = []
    for entry in traffic_entries:
        req_method = entry['method'].upper()
        req_path = entry['path']

        # Strip server base path to get the relative path
        if req_path.startswith(server_base_path):
            rel_path = req_path[len(server_base_path):]
        else:
            rel_path = req_path

        matched_op = None
        for op in operations:
            if op['method'] == req_method:
                regex = path_template_to_regex(op['path'])
                if re.match(regex, rel_path):
                    matched_op = op
                    break

        matches.append({
            'entry': entry,
            'operation': matched_op,
        })

    return matches


def parse_jacoco_xml(xml_path):
    """Parse JaCoCo XML report and return coverage ratios from report-level counters."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    coverage = {}
    # Only read direct children of the report element (report-level counters)
    for counter in root.findall('counter'):
        ctype = counter.get('type')
        missed = int(counter.get('missed', 0))
        covered = int(counter.get('covered', 0))
        total = missed + covered
        coverage[ctype] = covered / total if total > 0 else 0.0

    return coverage


def build_odg(spec, operations):
    """Build the Operation Dependency Graph.

    An edge from A to B exists when A's success response schema contains
    a property whose name and type match a request parameter of B.
    No self-loops.
    """
    odg = {op['operationId']: [] for op in operations}

    # Precompute request params for all operations
    op_request_params = {}
    for op in operations:
        params = get_request_params(spec, op['operation'], op.get('path_item_params'))
        op_request_params[op['operationId']] = params

    # Precompute response properties for all operations
    op_response_props = {}
    for op in operations:
        props = get_response_properties(spec, op['operation'])
        op_response_props[op['operationId']] = props

    # Build edges
    for op_a in operations:
        a_id = op_a['operationId']
        a_resp = op_response_props[a_id]

        for op_b in operations:
            b_id = op_b['operationId']
            if a_id == b_id:
                continue

            b_params = op_request_params[b_id]

            for prop_name, prop_type in a_resp.items():
                if prop_name in b_params and b_params[prop_name] == prop_type:
                    if b_id not in odg[a_id]:
                        odg[a_id].append(b_id)
                    break

    return odg


def compute_z_scores(tool_metrics):
    """Compute population Z-score normalization across tools."""
    tools = sorted(tool_metrics.keys())

    dimensions = {
        'operation_coverage': [tool_metrics[t]['operations_covered'] for t in tools],
        'fault_detection': [tool_metrics[t]['unique_faults'] for t in tools],
        'branch_coverage': [tool_metrics[t]['branch_coverage'] for t in tools],
    }

    z_scores = {t: {} for t in tools}

    for dim_name, values in dimensions.items():
        n = len(values)
        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / n
        std = math.sqrt(variance)

        for i, t in enumerate(tools):
            if std == 0:
                z_scores[t][dim_name] = 0.0
            else:
                z_scores[t][dim_name] = (values[i] - mean) / std

    for t in tools:
        z_scores[t]['composite'] = (
            z_scores[t]['operation_coverage'] +
            z_scores[t]['fault_detection'] +
            z_scores[t]['branch_coverage']
        )

    return z_scores


def generate_dot(odg, output_path):
    """Generate a Graphviz DOT file from the ODG adjacency list."""
    lines = ['digraph ODG {']
    lines.append('    rankdir=LR;')
    lines.append('    node [shape=box, style=filled, fillcolor="#e8f4fd"];')
    lines.append('')

    for op_id in sorted(odg.keys()):
        lines.append(f'    "{op_id}";')

    lines.append('')

    for op_id in sorted(odg.keys()):
        for dep in sorted(odg[op_id]):
            lines.append(f'    "{op_id}" -> "{dep}";')

    lines.append('}')

    with open(output_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


def main():
    # Load OpenAPI spec
    with open('/app/api_spec.yaml') as f:
        spec = yaml.safe_load(f)

    # Extract server base path
    servers = spec.get('servers', [])
    server_url = servers[0]['url'] if servers else ''
    parsed = urlparse(server_url)
    server_base_path = parsed.path.rstrip('/')

    # Extract all operations
    operations = extract_operations(spec)

    # Process traffic for each tool
    tool_metrics = {}
    traffic_dir = '/app/traffic'

    for traffic_file in sorted(glob.glob(os.path.join(traffic_dir, '*.jsonl'))):
        tool_name = Path(traffic_file).stem

        # Read traffic entries
        entries = []
        with open(traffic_file) as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))

        # Match traffic entries to operations
        matches = match_traffic_to_operations(entries, operations, server_base_path)

        # Compute metrics
        covered_ops = set()
        fault_messages = set()
        status_dist = {'2xx': 0, '4xx': 0, '5xx': 0}

        for m in matches:
            entry = m['entry']
            status = entry['status']

            if 200 <= status <= 299:
                status_dist['2xx'] += 1
                if m['operation']:
                    covered_ops.add(m['operation']['operationId'])
            elif 400 <= status <= 499:
                status_dist['4xx'] += 1
            elif 500 <= status <= 599:
                status_dist['5xx'] += 1
                # Extract unique fault message from response body
                resp_body = entry.get('response_body')
                if resp_body is None:
                    resp_body = {}
                elif isinstance(resp_body, str):
                    try:
                        resp_body = json.loads(resp_body)
                    except (json.JSONDecodeError, TypeError):
                        resp_body = {}
                if isinstance(resp_body, dict):
                    msg = resp_body.get('message', '')
                    if msg:
                        fault_messages.add(msg)

        # Parse JaCoCo coverage
        coverage_file = os.path.join('/app/coverage', f'{tool_name}.xml')
        jacoco = parse_jacoco_xml(coverage_file)

        tool_metrics[tool_name] = {
            'operations_covered': len(covered_ops),
            'total_operations': len(operations),
            'operation_coverage_ratio': len(covered_ops) / len(operations) if operations else 0,
            'unique_faults': len(fault_messages),
            'status_code_distribution': status_dist,
            'branch_coverage': round(jacoco.get('BRANCH', 0.0), 4),
            'line_coverage': round(jacoco.get('LINE', 0.0), 4),
            'method_coverage': round(jacoco.get('METHOD', 0.0), 4),
        }

    # Build ODG from spec
    odg = build_odg(spec, operations)

    # Compute Z-scores
    z_scores = compute_z_scores(tool_metrics)

    # Ranking: descending composite score
    tools_ranked = sorted(z_scores.keys(),
                          key=lambda t: z_scores[t]['composite'],
                          reverse=True)

    # Badges
    badges = {
        'gold_api_tester': tools_ranked[0],
        'bug_hunter': max(tool_metrics.keys(),
                          key=lambda t: tool_metrics[t]['unique_faults']),
    }

    # Assemble report
    report = {
        'operations': [
            {
                'operationId': op['operationId'],
                'method': op['method'],
                'path': op['path'],
            }
            for op in operations
        ],
        'operation_dependency_graph': odg,
        'tool_metrics': tool_metrics,
        'z_scores': z_scores,
        'ranking': tools_ranked,
        'badges': badges,
    }

    with open('/app/report.json', 'w') as f:
        json.dump(report, f, indent=2)

    # Generate DOT file
    generate_dot(odg, '/app/odg.dot')

    # Render SVG
    subprocess.run(['dot', '-Tsvg', '-o', '/app/odg.svg', '/app/odg.dot'], check=True)

    print("Analysis complete. Report written to /app/report.json")
    print(f"Operations: {len(operations)}")
    print(f"Tools analyzed: {list(tool_metrics.keys())}")
    print(f"Ranking: {tools_ranked}")


if __name__ == '__main__':
    main()
