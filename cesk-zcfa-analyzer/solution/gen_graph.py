#!/usr/bin/env python3
"""Generate DOT flow graph from analysis results for higher_order.scm."""


import sys
import subprocess

sys.path.insert(0, '/app')

from analysis import analyze


def main():
    with open('/app/programs/higher_order.scm') as f:
        program = f.read()

    flow = analyze(program)

    lines = ['digraph flow_analysis {']
    lines.append('    rankdir=LR;')

    # Collect all lambda labels that appear in flow sets
    all_labels = set()
    for var, labels in flow.items():
        if labels:
            all_labels.update(labels)

    # Lambda nodes (rectangular boxes)
    for label in sorted(all_labels):
        lines.append(f'    "L{label}" [shape=box];')

    # Variable nodes (ellipses) and edges
    for var in sorted(flow.keys()):
        if flow[var]:
            lines.append(f'    "{var}" [shape=ellipse];')
            for label in sorted(flow[var]):
                lines.append(f'    "L{label}" -> "{var}";')

    lines.append('}')

    dot_content = '\n'.join(lines) + '\n'

    with open('/app/flow_graph.dot', 'w') as f:
        f.write(dot_content)

    subprocess.run(
        ['dot', '-Tsvg', '-o', '/app/flow_graph.svg', '/app/flow_graph.dot'],
        check=True,
    )
    print('Generated flow_graph.dot and flow_graph.svg')


if __name__ == '__main__':
    main()
