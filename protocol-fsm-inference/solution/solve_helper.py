#!/usr/bin/env python3
"""
Solution: Protocol State Machine Inference, Minimization, Coverage, and Visualization.
"""

import struct
import json
import os
import glob
import re
import sqlite3
import subprocess
from collections import defaultdict


MAGIC = b'\x50\x46'


def parse_trace(filepath):
    """Parse a binary trace file into a list of (direction, code, payload) tuples."""
    with open(filepath, 'rb') as f:
        data = f.read()

    if len(data) < 4:
        return None
    if data[0:2] != MAGIC:
        return None

    msg_count = data[3]
    messages = []
    offset = 4

    for _ in range(msg_count):
        if offset + 4 > len(data):
            break
        direction = data[offset]
        code = data[offset + 1]
        payload_len = struct.unpack('>H', data[offset + 2:offset + 4])[0]
        offset += 4
        if offset + payload_len > len(data):
            break
        payload = data[offset:offset + payload_len]
        messages.append((direction, code, payload))
        offset += payload_len

    return messages


def extract_transitions(messages):
    """Extract (from_state, command, to_state) transitions from parsed messages."""
    transitions = []
    visited_states = {0}
    current_state = 0

    i = 0
    while i < len(messages) - 1:
        if messages[i][0] == 1:  # request
            command = messages[i][1]
            if i + 1 < len(messages) and messages[i + 1][0] == 2:  # response
                response_code = messages[i + 1][1]
                transitions.append((current_state, command, response_code))
                current_state = response_code
                visited_states.add(current_state)
                i += 2
            else:
                i += 1
        else:
            i += 1

    return transitions, visited_states


def build_fsm(all_transitions):
    """Build FSM from observed transitions across all traces."""
    states = set()
    trans_set = set()

    for trace_trans in all_transitions:
        for from_s, cmd, to_s in trace_trans:
            states.add(from_s)
            states.add(to_s)
            trans_set.add((from_s, cmd, to_s))

    return sorted(states), sorted(trans_set)


def compute_bisimulation(states, transitions):
    """Compute the coarsest bisimulation partition via partition refinement."""
    trans_map = defaultdict(lambda: defaultdict(set))
    all_labels = set()
    for from_s, cmd, to_s in transitions:
        trans_map[from_s][cmd].add(to_s)
        all_labels.add(cmd)

    sorted_labels = sorted(all_labels)

    # Initial partition: group states by their set of outgoing labels
    label_groups = defaultdict(list)
    for s in states:
        key = frozenset(trans_map[s].keys())
        label_groups[key].append(s)

    partition = [set(group) for group in label_groups.values()]

    def state_to_block_idx(state, part):
        for idx, block in enumerate(part):
            if state in block:
                return idx
        return -1

    # Iterative refinement
    changed = True
    while changed:
        changed = False
        new_partition = []

        for block in partition:
            if len(block) <= 1:
                new_partition.append(block)
                continue

            signatures = {}
            for s in block:
                sig_parts = []
                for label in sorted_labels:
                    targets = trans_map[s].get(label, set())
                    target_blocks = frozenset(
                        state_to_block_idx(t, partition) for t in targets
                    )
                    sig_parts.append(target_blocks)
                signatures[s] = tuple(sig_parts)

            groups = defaultdict(set)
            for s, sig in signatures.items():
                groups[sig].add(s)

            if len(groups) > 1:
                changed = True

            new_partition.extend(groups.values())

        partition = new_partition

    return partition


def parse_reference_dot(filepath):
    """Parse reference FSM from Graphviz DOT format, returning edge triples."""
    with open(filepath) as f:
        content = f.read()

    edges = re.findall(r'(\w+)\s*->\s*(\w+)\s*\[label="(\w+)"\]', content)
    return edges


def generate_dot(states, transitions, filepath, spec, merged_mapping=None):
    """Generate Graphviz DOT file for FSM."""
    code_to_state = {int(k): v for k, v in spec["response_codes"].items()}
    code_to_state[0] = "INITIAL"
    code_to_cmd = {int(k): v for k, v in spec["commands"].items()}

    with open(filepath, 'w') as f:
        f.write("digraph fsm {\n")
        f.write("    rankdir=LR;\n")
        f.write("    node [shape=circle];\n\n")

        if merged_mapping:
            node_names = set()
            for s in states:
                name = merged_mapping.get(s, code_to_state.get(s, "S%d" % s))
                node_names.add(name)

            for name in sorted(node_names):
                f.write("    %s;\n" % name)

            f.write("\n")
            seen_edges = set()
            for from_s, cmd, to_s in transitions:
                src = merged_mapping.get(from_s, code_to_state.get(from_s, "S%d" % from_s))
                dst = merged_mapping.get(to_s, code_to_state.get(to_s, "S%d" % to_s))
                cmd_name = code_to_cmd.get(cmd, "CMD%d" % cmd)
                edge = (src, dst, cmd_name)
                if edge not in seen_edges:
                    seen_edges.add(edge)
                    f.write("    %s -> %s [label=\"%s\"];\n" % (src, dst, cmd_name))
        else:
            for s in states:
                name = code_to_state.get(s, "S%d" % s)
                f.write("    %s;\n" % name)

            f.write("\n")
            for from_s, cmd, to_s in transitions:
                src = code_to_state.get(from_s, "S%d" % from_s)
                dst = code_to_state.get(to_s, "S%d" % to_s)
                cmd_name = code_to_cmd.get(cmd, "CMD%d" % cmd)
                f.write("    %s -> %s [label=\"%s\"];\n" % (src, dst, cmd_name))

        f.write("}\n")


def render_svg(dot_path, svg_path):
    """Render DOT file to SVG using graphviz."""
    subprocess.run(["dot", "-Tsvg", "-o", svg_path, dot_path], check=True)


def main():
    os.makedirs('/app/output', exist_ok=True)

    # Load protocol spec
    with open('/app/protocol_spec.json') as f:
        spec = json.load(f)

    # 1. Parse all traces
    trace_files = sorted(glob.glob('/app/traces/*.bin'))
    all_transitions = []
    all_visited_states = {}

    for tf in trace_files:
        messages = parse_trace(tf)
        if messages is None:
            continue
        trans, visited = extract_transitions(messages)
        trace_name = os.path.splitext(os.path.basename(tf))[0]
        all_transitions.append(trans)
        all_visited_states[trace_name] = visited

    # 2. Build FSM
    states, transitions = build_fsm(all_transitions)

    fsm_output = {
        'states': states,
        'transitions': [
            {'from': f, 'command': c, 'to': t}
            for f, c, t in transitions
        ],
        'num_states': len(states),
        'num_transitions': len(transitions)
    }

    with open('/app/output/fsm.json', 'w') as f:
        json.dump(fsm_output, f, indent=2)

    # 3. Generate FSM visualization
    generate_dot(states, transitions, '/app/output/fsm.dot', spec)
    render_svg('/app/output/fsm.dot', '/app/output/fsm.svg')

    # 4. Bisimulation minimization
    partition = compute_bisimulation(states, transitions)
    partition_sorted = [sorted(block) for block in partition]
    partition_sorted.sort(key=lambda x: x[0])

    merged = [cls for cls in partition_sorted if len(cls) > 1]

    min_output = {
        'equivalence_classes': partition_sorted,
        'num_states_before': len(states),
        'num_states_after': len(partition),
        'merged_states': merged
    }

    with open('/app/output/minimized_fsm.json', 'w') as f:
        json.dump(min_output, f, indent=2)

    # 5. Generate minimized FSM visualization
    code_to_state = {int(k): v for k, v in spec["response_codes"].items()}
    code_to_state[0] = "INITIAL"

    merged_mapping = {}
    for cls in partition_sorted:
        if len(cls) > 1:
            merged_name = "_".join(code_to_state.get(s, "S%d" % s) for s in cls)
            for s in cls:
                merged_mapping[s] = merged_name

    generate_dot(states, transitions, '/app/output/minimized_fsm.dot', spec, merged_mapping)
    render_svg('/app/output/minimized_fsm.dot', '/app/output/minimized_fsm.svg')

    # 6. Coverage gap analysis — parse reference from DOT
    ref_edges = parse_reference_dot('/app/reference.dot')

    state_to_code = {v: int(k) for k, v in spec["response_codes"].items()}
    state_to_code["INITIAL"] = 0
    cmd_to_code = {v: int(k) for k, v in spec["commands"].items()}

    ref_transitions = set()
    for src, dst, cmd in ref_edges:
        from_code = state_to_code[src]
        to_code = state_to_code[dst]
        cmd_code = cmd_to_code[cmd]
        ref_transitions.add((from_code, cmd_code, to_code))

    observed = set(transitions)
    uncovered = sorted(ref_transitions - observed)
    coverage_ratio = len(observed & ref_transitions) / len(ref_transitions)

    # Coverage from SQLite database
    conn = sqlite3.connect('/app/coverage.db')
    cursor = conn.execute("SELECT DISTINCT block_id FROM basic_block_coverage")
    all_blocks = {row[0] for row in cursor}
    conn.close()

    # Per-state trace count
    per_state_count = defaultdict(int)
    for trace_name, visited in all_visited_states.items():
        for s in visited:
            per_state_count[s] += 1

    coverage_output = {
        'total_unique_blocks': len(all_blocks),
        'transition_coverage': round(coverage_ratio, 4),
        'uncovered_transitions': [
            {'from': f, 'command': c, 'to': t}
            for f, c, t in uncovered
        ],
        'per_state_trace_count': {
            str(s): per_state_count[s]
            for s in sorted(per_state_count.keys())
        }
    }

    with open('/app/output/coverage_analysis.json', 'w') as f:
        json.dump(coverage_output, f, indent=2)

    print("Analysis complete. Output written to /app/output/")


if __name__ == '__main__':
    main()
