#!/usr/bin/env python3
"""
Generate Graphviz DOT and SVG visualizations for non-linearizable histories.

Reads results.json to identify non-linearizable histories, then produces
DOT files showing operations as nodes and real-time precedence as edges,
rendered to SVG via the dot command.
"""

import json
import os
import subprocess
import sys


def parse_history(history):
    """Parse raw history into paired operations."""
    ops = []
    invocations = {}
    for event in history:
        proc = event['process']
        typ = event['type']
        if typ == 'invoke':
            invocations[proc] = event
        elif typ in ('ok', 'fail', 'info'):
            if proc in invocations:
                inv = invocations.pop(proc)
                ops.append({
                    'process': proc,
                    'f': event['f'],
                    'value': event.get('value'),
                    'type': typ,
                    'invoke_index': inv['index'],
                    'complete_index': event['index'],
                })
    return ops


def format_value(f, value):
    """Format an operation's value for display."""
    if f == 'read':
        return ' -> {}'.format(value)
    elif f == 'write':
        return '({})'.format(value)
    elif f == 'cas':
        return '({} -> {})'.format(value[0], value[1])
    return ''


def generate_dot(history_name, history):
    """Generate DOT source for a non-linearizable history visualization."""
    ops = parse_history(history)
    # Include ok and info operations (fail ops didn't take effect)
    relevant = [op for op in ops if op['type'] in ('ok', 'info')]

    lines = [
        'digraph "{}" {{'.format(history_name),
        '  rankdir=TB;',
        '  label="Non-linearizable: {}";'.format(history_name),
        '  labelloc=t;',
        '  fontsize=14;',
        '  node [shape=box, style=filled, fontname="monospace", fontsize=10];',
        '  edge [color="#666666"];',
    ]

    for i, op in enumerate(relevant):
        val_str = format_value(op['f'], op['value'])
        type_tag = ' [info]' if op['type'] == 'info' else ''
        label = 'P{}: {}{}{}'.format(op['process'], op['f'], val_str, type_tag)
        if op['type'] == 'info':
            color = '#ffcccc'
        else:
            color = '#ffffcc'
        lines.append('  op{} [label="{}", fillcolor="{}"];'.format(i, label, color))

    # Add real-time precedence edges
    for i, a in enumerate(relevant):
        if a['type'] != 'ok':
            continue
        for j, b in enumerate(relevant):
            if i != j and a['complete_index'] < b['invoke_index']:
                # Check this is a direct edge (no intermediate op)
                is_direct = True
                for k, c in enumerate(relevant):
                    if k != i and k != j and c['type'] == 'ok':
                        if (a['complete_index'] < c['invoke_index'] and
                                c['complete_index'] < b['invoke_index']):
                            is_direct = False
                            break
                if is_direct:
                    lines.append('  op{} -> op{} [label="rt"];'.format(i, j))

    lines.append('}')
    return '\n'.join(lines)


def main():
    results_file = sys.argv[1] if len(sys.argv) > 1 else '/app/results.json'
    json_dir = sys.argv[2] if len(sys.argv) > 2 else '/tmp/json_histories'
    viz_dir = sys.argv[3] if len(sys.argv) > 3 else '/app/viz'

    os.makedirs(viz_dir, exist_ok=True)

    with open(results_file) as f:
        results = json.load(f)

    for edn_name, is_linear in results.items():
        if is_linear:
            continue

        # Load the corresponding JSON history
        json_name = edn_name[:-4] + '.json'
        json_path = os.path.join(json_dir, json_name)
        if not os.path.exists(json_path):
            continue

        with open(json_path) as f:
            history = json.load(f)

        base_name = edn_name[:-4]
        dot_path = os.path.join(viz_dir, '{}.dot'.format(base_name))
        svg_path = os.path.join(viz_dir, '{}.svg'.format(base_name))

        # Generate DOT source
        dot_content = generate_dot(base_name, history)
        with open(dot_path, 'w') as f:
            f.write(dot_content)

        # Render SVG with graphviz
        subprocess.run(
            ['dot', '-Tsvg', '-o', svg_path, dot_path],
            check=True,
            capture_output=True,
        )


if __name__ == '__main__':
    main()
