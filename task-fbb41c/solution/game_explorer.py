
"""Game tree explorer with Graphviz DOT/SVG visualization.

BFS-explores a game tree from the initial state to a given depth using
the GdlQueryEngine, generates a Graphviz DOT file, renders to SVG via
the `dot` CLI, and writes an analysis JSON report.
"""

import json
import subprocess
import hashlib
from gdl_query import GdlQueryEngine


def _state_id(state):
    """Generate a short deterministic ID for a game state."""
    s = str(sorted(state))
    return 's_' + hashlib.md5(s.encode()).hexdigest()[:10]


def explore_and_visualize(pl_path, depth, dot_output, svg_output, json_output):
    """BFS-explore the game tree and produce DOT, SVG, and analysis JSON.

    Args:
        pl_path: Path to the transpiled .pl game file.
        depth: Maximum BFS depth to explore.
        dot_output: Path to write the DOT file.
        svg_output: Path to write the SVG rendering.
        json_output: Path to write the analysis JSON.
    """
    engine = GdlQueryEngine(pl_path)
    roles = engine.get_roles()
    init = engine.get_initial_state()

    visited = {init: _state_id(init)}
    queue = [(init, 0)]
    transitions = []
    terminal_count = 0
    branching_counts = []

    while queue:
        current, d = queue.pop(0)
        if d >= depth:
            continue

        if engine.is_terminal(current):
            terminal_count += 1
            continue

        # Collect legal moves per role
        role_moves = {}
        for role in roles:
            moves = engine.get_legal_moves(current, role)
            role_moves[role] = list(moves)

        # Enumerate all joint moves (Cartesian product)
        joint_moves = [{}]
        for role in roles:
            new_joints = []
            for jm in joint_moves:
                for move in role_moves[role]:
                    new_jm = dict(jm)
                    new_jm[role] = move
                    new_joints.append(new_jm)
            joint_moves = new_joints

        branching_counts.append(len(joint_moves))

        for jm in joint_moves:
            ns = engine.get_next_state(current, jm)
            if ns not in visited:
                visited[ns] = _state_id(ns)
                queue.append((ns, d + 1))

            label_parts = []
            for r in roles:
                label_parts.append(r + ':' + '.'.join(jm[r]))
            label = ', '.join(label_parts)
            transitions.append((visited[current], visited[ns], label))

    # Generate DOT
    dot_lines = [
        'digraph game_tree {',
        '    rankdir=TB;',
        '    node [shape=box, fontsize=10];',
        '    edge [fontsize=8];',
    ]
    for state, sid in visited.items():
        dot_lines.append('    "' + sid + '" [label="' + sid + '"];')
    for src, dst, label in transitions:
        safe_label = label.replace('"', '\\"')
        dot_lines.append(
            '    "' + src + '" -> "' + dst + '" [label="' + safe_label + '"];'
        )
    dot_lines.append('}')

    with open(dot_output, 'w') as f:
        f.write('\n'.join(dot_lines) + '\n')

    # Render SVG via Graphviz dot
    subprocess.run(
        ['dot', '-Tsvg', '-o', svg_output, dot_output],
        check=True, timeout=30
    )

    # Compute analysis
    avg_branching = (
        sum(branching_counts) / len(branching_counts)
        if branching_counts else 0.0
    )

    analysis = {
        'roles': roles,
        'total_states': len(visited),
        'total_transitions': len(transitions),
        'depth': depth,
        'terminal_states_found': terminal_count,
        'branching_factor': round(avg_branching, 2),
    }

    with open(json_output, 'w') as f:
        json.dump(analysis, f, indent=2)
