#!/usr/bin/env python3
"""Generates game state graphs as Graphviz DOT/SVG from GDL game descriptions."""

import os
import hashlib
import subprocess
import itertools


def generate_state_graph(kif_path, output_dot, max_depth=3):
    """Explore the game tree via BFS and produce a Graphviz DOT file.

    Each node is a game state (labeled with sorted propositions).
    Each edge is a joint move. For multi-player games, at most 4 moves
    per role are explored to bound the graph size.
    """
    import sys
    sys.path.insert(0, '/app')
    from gdl_reasoner import GDLReasoner

    reasoner = GDLReasoner(kif_path)
    roles = reasoner.get_roles()
    init_state = reasoner.get_initial_state()

    def state_id(state):
        key = '|'.join(sorted(state))
        return 's' + hashlib.md5(key.encode()).hexdigest()[:8]

    nodes = {}
    edges = []
    queue = [(frozenset(init_state), 0)]
    visited = set()

    while queue:
        state_fs, depth = queue.pop(0)
        state = set(state_fs)
        sid = state_id(state)

        if sid in visited:
            continue
        visited.add(sid)
        nodes[sid] = state

        if depth >= max_depth or reasoner.is_terminal(state):
            continue

        legal = reasoner.get_legal_moves(state)

        if len(roles) == 1:
            role = roles[0]
            for move in legal.get(role, []):
                moves = {role: move}
                next_state = reasoner.get_next_state(state, moves)
                nsid = state_id(next_state)
                edges.append((sid, nsid, f'{role}:{move}'))
                if nsid not in visited:
                    queue.append((frozenset(next_state), depth + 1))
        else:
            # Multi-player: limit moves per role to bound graph size
            role_moves = [
                [(r, m) for m in legal.get(r, [])[:4]]
                for r in roles
            ]
            for combo in itertools.product(*role_moves):
                moves = {r: m for r, m in combo}
                next_state = reasoner.get_next_state(state, moves)
                nsid = state_id(next_state)
                label = ', '.join(f'{r}:{m}' for r, m in combo)
                edges.append((sid, nsid, label))
                if nsid not in visited:
                    queue.append((frozenset(next_state), depth + 1))

    os.makedirs(os.path.dirname(output_dot), exist_ok=True)
    with open(output_dot, 'w') as f:
        f.write('digraph game_states {\n')
        f.write('    rankdir=TB;\n')
        f.write('    node [shape=box, fontsize=9, fontname="monospace"];\n')
        f.write('    edge [fontsize=7];\n')
        for sid, state in nodes.items():
            label = '\\n'.join(sorted(state))
            label = label.replace('"', '\\"')
            f.write(f'    "{sid}" [label="{label}"];\n')
        for src, dst, label in edges:
            label = label.replace('"', '\\"')
            f.write(f'    "{src}" -> "{dst}" [label="{label}"];\n')
        f.write('}\n')

    return output_dot


def render_svg(dot_path, svg_path):
    """Compile a DOT file to SVG using the graphviz dot command."""
    os.makedirs(os.path.dirname(svg_path), exist_ok=True)
    result = subprocess.run(
        ['dot', '-Tsvg', dot_path, '-o', svg_path],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        raise RuntimeError(f'dot command failed: {result.stderr}')
    return svg_path
