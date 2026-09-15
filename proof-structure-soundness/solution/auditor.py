#!/usr/bin/env python3
"""
Proof Structure Soundness Auditor

Parses a JasperGold Tcl proof plan and SMT-LIB2 constraint files,
uses Z3 to verify case-split exhaustiveness, detects circular
dependencies in assume-guarantee compositions, and computes
per-node decomposition soundness.
"""

import json
import re
from collections import defaultdict
from z3 import Solver, Int, And, Or, Not, sat, parse_smt2_string


def parse_tcl_proof_plan(path):
    """Parse JasperGold Tcl proof plan to extract proof hierarchy."""
    nodes = {}
    guarantees = {}
    assumptions = defaultdict(list)
    split_configs = {}
    partition_configs = {}
    partition_values = {}
    stopat_configs = {}
    parent_map = {}

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            m = re.match(r'proof_node\s+(\S+)\s+(.*)', line)
            if m:
                nid = m.group(1)
                rest = m.group(2)
                strategy = re.search(r'-strategy\s+(\S+)', rest)
                parent = re.search(r'-parent\s+(\S+)', rest)
                status = re.search(r'-status\s+(\S+)', rest)
                nodes[nid] = {
                    'strategy': strategy.group(1) if strategy else '',
                    'status': status.group(1) if status else None,
                }
                if parent:
                    parent_map[nid] = parent.group(1)
                continue

            m = re.match(r'guarantee\s+(\S+)\s+(\S+)', line)
            if m:
                guarantees[m.group(1)] = m.group(2)
                continue

            m = re.match(r'assume\s+(\S+)\s+(\S+):(\S+)', line)
            if m:
                assumptions[m.group(1)].append(f"{m.group(2)}:{m.group(3)}")
                continue

            m = re.match(
                r'split_config\s+(\S+)\s+-signal\s+(\S+)\s+-constraint\s+(\S+)',
                line,
            )
            if m:
                split_configs[m.group(1)] = {
                    'signal': m.group(2),
                    'constraint_file': m.group(3),
                }
                continue

            m = re.match(r'partition_config\s+(\S+)\s+-signal\s+(\S+)', line)
            if m:
                partition_configs[m.group(1)] = m.group(2)
                continue

            m = re.match(r'partition_value\s+(\S+)\s+(\S+)', line)
            if m:
                partition_values[m.group(1)] = m.group(2)
                continue

            m = re.match(r'stopat_config\s+(\S+)\s+-signals\s+\{([^}]*)\}', line)
            if m:
                stopat_configs[m.group(1)] = m.group(2).split()
                continue

    return (
        nodes, guarantees, assumptions, split_configs,
        partition_configs, partition_values, stopat_configs, parent_map,
    )


def build_children_map(parent_map):
    children = defaultdict(list)
    for child_id, parent_id in parent_map.items():
        children[parent_id].append(child_id)
    return children


# ---------------------------------------------------------------------------
# SMT-based case-split exhaustiveness checking
# ---------------------------------------------------------------------------

def check_split_completeness_z3(constraint_file, signal_name, design_spec):
    """Use Z3 to verify that case-split predicates exhaust the signal domain."""
    with open(constraint_file) as f:
        smt_content = f.read()

    case_names = re.findall(r'\(define-fun\s+(case_\w+)\s+\(\)\s+Bool', smt_content)
    if not case_names:
        return None

    # Build exhaustiveness query: in_domain AND NOT(any case)
    case_or = ' '.join(case_names)
    augmented = smt_content + (
        f"\n(assert in_domain)\n"
        f"(assert (not (or {case_or})))\n"
    )

    try:
        assertions = parse_smt2_string(augmented)
        s = Solver()
        s.add(assertions)
        result = s.check()
    except Exception:
        return None

    if result != sat:
        return None  # UNSAT → split is exhaustive

    # Split is incomplete — enumerate covered vs missing values
    encoding = design_spec['signals'][signal_name]
    reverse_enc = {v: k for k, v in encoding.items()}
    all_values = set(encoding.values())

    var_m = re.search(r'\(declare-const\s+(\w+)\s+Int\)', smt_content)
    var_name = var_m.group(1) if var_m else signal_name

    covered = set()
    missing = set()

    for val in all_values:
        # Check: in_domain AND (var == val) AND (some case covers it)
        chk = smt_content + (
            f"\n(assert in_domain)\n"
            f"(assert (= {var_name} {val}))\n"
            f"(assert (or {case_or}))\n"
        )
        try:
            a = parse_smt2_string(chk)
            s2 = Solver()
            s2.add(a)
            if s2.check() == sat:
                covered.add(val)
            else:
                missing.add(val)
        except Exception:
            missing.add(val)

    if missing:
        return {
            'signal': signal_name,
            'covered': sorted(reverse_enc[v] for v in covered if v in reverse_enc),
            'missing': sorted(reverse_enc[v] for v in missing if v in reverse_enc),
        }
    return None


# ---------------------------------------------------------------------------
# Partition completeness checking
# ---------------------------------------------------------------------------

def check_partition_completeness(node_id, signal, pv_map, children_map, design_spec):
    encoding = design_spec['signals'][signal]
    reverse_enc = {v: k for k, v in encoding.items()}
    all_vals = set(encoding.values())

    covered = set()
    for cid in children_map.get(node_id, []):
        if cid in pv_map:
            covered.add(int(pv_map[cid]))

    missing = all_vals - covered
    if missing:
        return {
            'node_id': node_id,
            'signal': signal,
            'covered': sorted(reverse_enc[v] for v in sorted(covered) if v in reverse_enc),
            'missing': sorted(reverse_enc[v] for v in sorted(missing) if v in reverse_enc),
        }
    return None


# ---------------------------------------------------------------------------
# Circular dependency detection (SCC)
# ---------------------------------------------------------------------------

def find_sccs(graph, node_set):
    """Tarjan's algorithm for strongly connected components."""
    idx = [0]
    stack, lowlink, index, on_stack = [], {}, {}, {}
    sccs = []

    def _connect(v):
        index[v] = lowlink[v] = idx[0]
        idx[0] += 1
        stack.append(v)
        on_stack[v] = True
        for w in graph.get(v, set()):
            if w not in index:
                _connect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif on_stack.get(w):
                lowlink[v] = min(lowlink[v], index[w])
        if lowlink[v] == index[v]:
            scc = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                scc.append(w)
                if w == v:
                    break
            if len(scc) >= 2:
                sccs.append(sorted(scc))

    for v in sorted(node_set):
        if v not in index:
            _connect(v)
    return sccs


def build_ag_graph(ag_id, children_map, assumptions):
    child_ids = set(children_map[ag_id])
    graph = defaultdict(set)
    for cid in child_ids:
        for ref in assumptions.get(cid, []):
            target = ref.split(':')[0]
            if target in child_ids:
                graph[cid].add(target)
    return graph, child_ids


def find_all_cycles(nodes, children_map, assumptions):
    cycles = []
    for nid, node in nodes.items():
        if node['strategy'] == 'assume_guarantee':
            g, cids = build_ag_graph(nid, children_map, assumptions)
            cycles.extend(find_sccs(g, cids))
    return cycles


# ---------------------------------------------------------------------------
# Decomposition soundness
# ---------------------------------------------------------------------------

def compute_soundness(nodes, children_map, assumptions, split_configs,
                      partition_configs, partition_values, design_spec):
    soundness = {}

    def _compute(nid):
        strat = nodes[nid]['strategy']
        if strat == 'leaf':
            return True

        children_ok = True
        for cid in children_map.get(nid, []):
            if nodes[cid]['strategy'] != 'leaf':
                if not _compute(cid):
                    children_ok = False

        own_ok = True
        if strat == 'assume_guarantee':
            g, cids = build_ag_graph(nid, children_map, assumptions)
            if find_sccs(g, cids):
                own_ok = False
        elif strat == 'case_split' and nid in split_configs:
            cfg = split_configs[nid]
            if check_split_completeness_z3(cfg['constraint_file'], cfg['signal'], design_spec):
                own_ok = False
        elif strat == 'partition' and nid in partition_configs:
            if check_partition_completeness(
                nid, partition_configs[nid], partition_values, children_map, design_spec
            ):
                own_ok = False

        soundness[nid] = own_ok and children_ok
        return soundness[nid]

    # Find root nodes (no parent)
    has_parent = set()
    for clist in children_map.values():
        has_parent.update(clist)
    roots = set(nodes.keys()) - has_parent

    for root in roots:
        _compute(root)
    return soundness


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    (nodes, guarantees, assumptions, split_configs,
     partition_configs, partition_values, stopat_configs,
     parent_map) = parse_tcl_proof_plan('/app/proof_plan.tcl')

    with open('/app/design_spec.json') as f:
        design_spec = json.load(f)

    children_map = build_children_map(parent_map)

    # Circular dependencies
    cycles = find_all_cycles(nodes, children_map, assumptions)

    # Incomplete case-splits
    incomplete_splits = []
    for nid, cfg in sorted(split_configs.items()):
        issue = check_split_completeness_z3(
            cfg['constraint_file'], cfg['signal'], design_spec,
        )
        if issue:
            issue['node_id'] = nid
            incomplete_splits.append(issue)

    # Decomposition soundness
    soundness = compute_soundness(
        nodes, children_map, assumptions, split_configs,
        partition_configs, partition_values, design_spec,
    )

    report = {
        'overall_sound': all(soundness.values()),
        'circular_dependencies': [{'cycle': c} for c in cycles],
        'incomplete_case_splits': incomplete_splits,
        'decomposition_soundness': soundness,
    }

    with open('/app/audit_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Audit complete. Overall sound: {report['overall_sound']}")
    print(f"  Cycles found: {len(cycles)}")
    print(f"  Incomplete splits: {len(incomplete_splits)}")


if __name__ == '__main__':
    main()
