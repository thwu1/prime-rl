#!/usr/bin/env python3
"""
Hubris RTOS IPC dependency graph and scheduling safety analyzer.

Performs comprehensive scheduling safety analysis:
1. Builds the IPC dependency graph from task-slot declarations
2. Generates Graphviz DOT graph with inversion highlighting
3. Detects direct priority inversions
4. Finds IPC cycles via Tarjan's SCC algorithm
5. Computes max call depth (longest simple path) per task
6. Computes effective priorities under Priority Inheritance Protocol
7. Computes fault cascade analysis (affected tasks, danger scores)
8. Suggests optimal priority reassignment via SCC condensation
"""


import json
import subprocess
import sys
import tomllib
from collections import defaultdict, deque


def load_config(path):
    with open(path, 'rb') as f:
        return tomllib.load(f)


def resolve_task_slot_target(slot):
    if isinstance(slot, str):
        return slot
    elif isinstance(slot, dict):
        values = list(slot.values())
        if len(values) == 1:
            return values[0]
    return None


def build_graph(config):
    tasks = config.get('tasks', {})
    priorities = {}
    adjacency = defaultdict(list)

    for task_name, task_conf in tasks.items():
        priorities[task_name] = task_conf.get('priority', 0)
        for slot in task_conf.get('task-slots', []):
            target = resolve_task_slot_target(slot)
            if target and target in tasks:
                adjacency[task_name].append(target)

    return priorities, adjacency


def build_reverse_adjacency(all_nodes, adjacency):
    reverse_adj = defaultdict(list)
    for sender in all_nodes:
        for target in adjacency.get(sender, []):
            reverse_adj[target].append(sender)
    return reverse_adj


def find_direct_inversions(priorities, adjacency):
    inversions = []
    for sender, targets in adjacency.items():
        for target in targets:
            if priorities[sender] < priorities[target]:
                inversions.append({
                    'sender': sender,
                    'sender_priority': priorities[sender],
                    'target': target,
                    'target_priority': priorities[target],
                })
    inversions.sort(key=lambda x: (x['sender'], x['target']))
    return inversions


def tarjan_scc(all_nodes, adjacency):
    index_counter = [0]
    stack = []
    on_stack = set()
    indices = {}
    lowlinks = {}
    sccs = []

    def strongconnect(v):
        indices[v] = index_counter[0]
        lowlinks[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)

        for w in adjacency.get(v, []):
            if w not in indices:
                strongconnect(w)
                lowlinks[v] = min(lowlinks[v], lowlinks[w])
            elif w in on_stack:
                lowlinks[v] = min(lowlinks[v], indices[w])

        if lowlinks[v] == indices[v]:
            scc = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                scc.append(w)
                if w == v:
                    break
            sccs.append(sorted(scc))

    for node in sorted(all_nodes):
        if node not in indices:
            strongconnect(node)

    return sccs


def find_cycles(all_nodes, adjacency):
    sccs = tarjan_scc(all_nodes, adjacency)
    cycles = [scc for scc in sccs if len(scc) >= 2]
    cycles.sort(key=lambda c: c[0])
    return cycles


def compute_max_call_depth(all_nodes, adjacency):
    depths = {}

    def dfs(node, visited):
        max_depth = 0
        for neighbor in adjacency.get(node, []):
            if neighbor not in visited:
                visited.add(neighbor)
                depth = 1 + dfs(neighbor, visited)
                max_depth = max(max_depth, depth)
                visited.discard(neighbor)
        return max_depth

    for node in all_nodes:
        visited = {node}
        depths[node] = dfs(node, visited)

    return depths


def compute_pip_effective_priorities(all_nodes, adjacency, priorities):
    """Compute effective priority under Priority Inheritance Protocol.

    For each task T, PIP_effective(T) = min(T.priority, min{S.priority :
    there exists a directed path from S to T in the IPC graph}).

    Uses BFS on the reverse IPC graph to find all transitive callers.
    """
    reverse_adj = build_reverse_adjacency(all_nodes, adjacency)

    pip = {}
    for task in all_nodes:
        # BFS from task in reverse graph to find task + all transitive callers
        visited = {task}
        queue = deque([task])
        while queue:
            current = queue.popleft()
            for caller in reverse_adj.get(current, []):
                if caller not in visited:
                    visited.add(caller)
                    queue.append(caller)
        # Effective priority = min priority among task and all transitive callers
        pip[task] = min(priorities[node] for node in visited)

    return pip


def compute_fault_cascades(all_nodes, adjacency, priorities):
    """Compute fault cascade analysis for each task.

    The fault cascade of task T = all tasks that have a directed IPC path
    reaching T (transitive callers). If T faults, these tasks could be
    transitively disrupted because they may be blocked on T through IPC chains.

    The danger score = count of affected tasks with strictly higher scheduling
    priority (lower priority number) than the faulting task.
    """
    reverse_adj = build_reverse_adjacency(all_nodes, adjacency)

    cascades = {}
    for task in all_nodes:
        # BFS from task in reverse graph, excluding task itself from results
        visited = {task}  # mark task visited to prevent cycle re-inclusion
        queue = deque()
        for caller in reverse_adj.get(task, []):
            if caller not in visited:
                visited.add(caller)
                queue.append(caller)
        while queue:
            current = queue.popleft()
            for caller in reverse_adj.get(current, []):
                if caller not in visited:
                    visited.add(caller)
                    queue.append(caller)

        affected = sorted(visited - {task})
        cascade_size = len(affected)
        danger = sum(1 for t in affected if priorities[t] < priorities[task])

        cascades[task] = {
            'affected_tasks': affected,
            'cascade_size': cascade_size,
            'danger_score': danger,
        }

    return cascades


def compute_suggested_priorities(all_nodes, adjacency):
    sccs = tarjan_scc(all_nodes, adjacency)

    node_to_scc = {}
    for i, scc in enumerate(sccs):
        for node in scc:
            node_to_scc[node] = i

    condensation = defaultdict(set)
    for sender in all_nodes:
        for target in adjacency.get(sender, []):
            s_scc = node_to_scc[sender]
            t_scc = node_to_scc[target]
            if s_scc != t_scc:
                condensation[s_scc].add(t_scc)

    jefe_scc = node_to_scc.get('jefe')
    idle_scc = node_to_scc.get('idle')

    longest_path = {}

    def longest_to_jefe(scc_id, visited):
        if scc_id in longest_path and scc_id not in visited:
            return longest_path[scc_id]
        if scc_id == jefe_scc:
            return 0

        visited.add(scc_id)
        max_dist = -1
        for neighbor in condensation.get(scc_id, set()):
            if neighbor not in visited:
                d = longest_to_jefe(neighbor, visited)
                if d >= 0:
                    max_dist = max(max_dist, 1 + d)
        visited.discard(scc_id)

        if max_dist >= 0:
            longest_path[scc_id] = max_dist
        return max_dist

    for i in range(len(sccs)):
        longest_to_jefe(i, set())

    max_prio = max((v for v in longest_path.values()), default=0)

    suggested = {}
    for node in all_nodes:
        scc_id = node_to_scc[node]
        if node == 'jefe':
            suggested[node] = 0
        elif node == 'idle':
            suggested[node] = max_prio + 1
        elif scc_id in longest_path:
            suggested[node] = longest_path[scc_id]
        else:
            suggested[node] = max_prio + 1

    return suggested


def generate_dot(all_nodes, adjacency, priorities, inversions, output_path):
    inversion_set = set()
    for inv in inversions:
        inversion_set.add((inv['sender'], inv['target']))

    lines = ['digraph hubris_ipc {']
    lines.append('    rankdir=LR;')
    lines.append('    node [shape=box, style=filled, fillcolor=lightyellow];')
    lines.append('')

    for node in sorted(all_nodes):
        prio = priorities.get(node, '?')
        lines.append(f'    {node} [label="{node}\\nprio={prio}"];')

    lines.append('')

    for sender in sorted(all_nodes):
        for target in sorted(adjacency.get(sender, [])):
            if (sender, target) in inversion_set:
                lines.append(
                    f'    {sender} -> {target} '
                    f'[color=red, penwidth=2.0, label="INVERSION"];'
                )
            else:
                lines.append(f'    {sender} -> {target};')

    lines.append('}')

    with open(output_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


def render_svg(dot_path, svg_path):
    try:
        result = subprocess.run(
            ['dot', '-Tsvg', dot_path, '-o', svg_path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"Warning: dot command failed: {result.stderr}", file=sys.stderr)
            return False
        return True
    except FileNotFoundError:
        print("Warning: graphviz 'dot' not found, skipping SVG render", file=sys.stderr)
        return False


def analyze(config_path, output_dir):
    config = load_config(config_path)
    priorities, adjacency = build_graph(config)
    all_nodes = set(config.get('tasks', {}).keys())

    inversions = find_direct_inversions(priorities, adjacency)
    cycles = find_cycles(all_nodes, adjacency)
    depths = compute_max_call_depth(all_nodes, adjacency)
    pip = compute_pip_effective_priorities(all_nodes, adjacency, priorities)
    cascades = compute_fault_cascades(all_nodes, adjacency, priorities)
    suggested = compute_suggested_priorities(all_nodes, adjacency)

    dot_path = f'{output_dir}/ipc_graph.dot'
    svg_path = f'{output_dir}/ipc_graph.svg'
    json_path = f'{output_dir}/analysis.json'

    generate_dot(all_nodes, adjacency, priorities, inversions, dot_path)
    render_svg(dot_path, svg_path)

    report = {
        'direct_inversions': inversions,
        'cycles': cycles,
        'max_call_depth': depths,
        'pip_effective_priorities': pip,
        'fault_cascade': cascades,
        'suggested_priorities': suggested,
    }

    with open(json_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Direct inversions: {len(inversions)}")
    print(f"IPC cycles: {len(cycles)}")
    print(f"Max blocking depth: {max(depths.values())}")
    print(f"\nPIP effective priorities:")
    for task in sorted(pip.keys()):
        orig = priorities[task]
        eff = pip[task]
        boost = f" (boosted from {orig})" if eff != orig else ""
        print(f"  {task}: {eff}{boost}")
    print(f"\nFault cascade summary:")
    for task in sorted(cascades.keys(), key=lambda t: -cascades[t]['danger_score']):
        c = cascades[task]
        if c['cascade_size'] > 0:
            print(f"  {task}: cascade={c['cascade_size']}, danger={c['danger_score']}")
    print(f"\nSuggested priorities:")
    for task in sorted(suggested.keys()):
        print(f"  {task}: {priorities[task]} -> {suggested[task]}")

    return report


if __name__ == '__main__':
    config_path = sys.argv[1] if len(sys.argv) > 1 else '/app/hubris_app.toml'
    output_dir = sys.argv[2] if len(sys.argv) > 2 else '/app'
    analyze(config_path, output_dir)
