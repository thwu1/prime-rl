#!/usr/bin/env python3
"""
Corrected Jepsen/Elle consistency checker.

Fixes bugs in /app/checker.py:
1. EDN parser: uses edn_format library to handle tagged literals (#inst etc.)
2. extract_transactions: correctly maps :fail to aborted, :info to indeterminate
3. build_dep_graph: adds rw anti-dependency edges for empty reads
4. classify_cycles: correct G-single (1 rw) vs G2-item (2+ rw) classification
"""

import json
import sys
import os
from collections import defaultdict

import edn_format

sys.setrecursionlimit(10000)


# ---- EDN handling via edn_format library ----

def edn_to_python(obj):
    """Convert edn_format objects to plain Python types."""
    if hasattr(obj, 'name') and not isinstance(obj, str):
        return ':' + str(obj.name)
    elif hasattr(obj, 'items') and hasattr(obj, 'keys'):
        return {edn_to_python(k): edn_to_python(v) for k, v in obj.items()}
    elif isinstance(obj, str):
        return obj
    elif hasattr(obj, '__iter__'):
        return [edn_to_python(x) for x in obj]
    else:
        return obj


def parse_history(path):
    """Parse a Jepsen EDN history file into plain Python data."""
    with open(path) as f:
        data = edn_format.loads(f.read())
    return edn_to_python(data)


# ---- Transaction Extraction ----

def extract_transactions(history):
    """
    Extract transactions from Jepsen invoke/completion history.
    Correctly maps :ok to committed, :fail to aborted, :info to indeterminate.
    """
    txns = []
    pending = {}
    txn_counter = 0

    for op in history:
        op_type = op.get(':type', '')
        process = op.get(':process', -1)

        if op_type == ':invoke':
            pending[process] = op
        elif op_type in (':ok', ':fail', ':info'):
            invoke = pending.pop(process, None)
            if invoke is not None:
                txn_counter += 1
                if op_type == ':ok':
                    status = 'committed'
                elif op_type == ':fail':
                    status = 'aborted'
                else:
                    status = 'indeterminate'
                txns.append({
                    'id': txn_counter,
                    'status': status,
                    'ops': normalize_ops(op.get(':value', []))
                })

    return txns


def normalize_ops(value):
    """Normalize operation format: strip keyword prefix from op type."""
    ops = []
    for micro_op in value:
        op_type = micro_op[0]
        if isinstance(op_type, str) and op_type.startswith(':'):
            op_type = op_type[1:]
        ops.append([op_type] + list(micro_op[1:]))
    return ops


# ---- Anomaly Detection ----

def detect_g1a(txns):
    """G1a: committed txn reads data from an aborted txn."""
    aborted_writes = set()
    for t in txns:
        if t['status'] == 'aborted':
            for op in t['ops']:
                if op[0] == 'append':
                    aborted_writes.add(op[2])

    if not aborted_writes:
        return False

    for t in txns:
        if t['status'] == 'committed':
            for op in t['ops']:
                if op[0] == 'r' and op[2] is not None:
                    for v in op[2]:
                        if v in aborted_writes:
                            return True
    return False


def detect_g1b(txns):
    """G1b: committed txn observes intermediate state of another committed txn."""
    committed = [t for t in txns if t['status'] == 'committed']

    for t in committed:
        appends_by_key = defaultdict(list)
        for op in t['ops']:
            if op[0] == 'append':
                appends_by_key[op[1]].append(op[2])

        for key, vals in appends_by_key.items():
            if len(vals) < 2:
                continue
            val_set = set(vals)

            for t2 in committed:
                if t2['id'] == t['id']:
                    continue
                for op in t2['ops']:
                    if (op[0] == 'r' and op[1] == key
                            and op[2] is not None):
                        observed = set(op[2]) & val_set
                        if 0 < len(observed) < len(vals):
                            return True
    return False


def infer_version_order(committed):
    """Infer version order per key from read observations."""
    val_to_txn = {}
    key_vals = defaultdict(set)

    for t in committed:
        for op in t['ops']:
            if op[0] == 'append':
                val_to_txn[op[2]] = t['id']
                key_vals[op[1]].add(op[2])

    key_order = {}
    for key, vals in key_vals.items():
        before = defaultdict(set)
        for t in committed:
            for op in t['ops']:
                if op[0] == 'r' and op[1] == key and op[2]:
                    seq = [v for v in op[2] if v in vals]
                    for i in range(len(seq)):
                        for j in range(i + 1, len(seq)):
                            before[seq[j]].add(seq[i])

        remaining = set(vals)
        order = []
        while remaining:
            ready = sorted(
                v for v in remaining
                if not (before.get(v, set()) & remaining)
            )
            if not ready:
                ready = [min(remaining)]
            order.extend(ready)
            remaining -= set(ready)

        key_order[key] = order

    return key_order, val_to_txn


def build_dep_graph(committed, key_order, val_to_txn):
    """Build transaction dependency graph with ww, wr, rw edges.

    Includes rw anti-dependency edges for the empty-read case: when a
    transaction reads an empty list for a key, it observed the initial
    (pre-write) version and has an anti-dependency to the first writer.
    """
    edges = defaultdict(set)

    for key, order in key_order.items():
        order_set = set(order)

        # WW edges
        for i in range(len(order) - 1):
            t1 = val_to_txn[order[i]]
            t2 = val_to_txn[order[i + 1]]
            if t1 != t2:
                edges[(t1, t2)].add('ww')

        # WR and RW edges
        for t in committed:
            for op in t['ops']:
                if op[0] != 'r' or op[1] != key:
                    continue

                reader_id = t['id']
                read_vals = op[2] if op[2] else []
                known = [v for v in read_vals if v in order_set]

                if not known:
                    # Empty read: saw the initial version (before any writes)
                    # RW anti-dependency to the first writer
                    if order:
                        first_writer = val_to_txn[order[0]]
                        if first_writer != reader_id:
                            edges[(reader_id, first_writer)].add('rw')
                else:
                    last_val = known[-1]
                    idx = order.index(last_val)
                    writer_id = val_to_txn[last_val]

                    # WR: writer -> reader
                    if writer_id != reader_id:
                        edges[(writer_id, reader_id)].add('wr')

                    # RW: reader -> next writer (anti-dependency)
                    for j in range(idx + 1, len(order)):
                        next_writer = val_to_txn[order[j]]
                        if next_writer != writer_id:
                            if next_writer != reader_id:
                                edges[(reader_id, next_writer)].add('rw')
                            break

    return edges


def find_all_cycles(edges, node_ids):
    """Find all simple cycles via DFS. Deduplicates by minimum node."""
    adj = defaultdict(list)
    for (s, d), types in edges.items():
        adj[s].append((d, frozenset(types)))

    nodes = sorted(node_ids)
    cycles = []

    for start in nodes:
        def dfs(cur, path, epath, visited):
            for nbr, etypes in adj[cur]:
                if nbr == start and len(path) > 1:
                    if start == min(path):
                        cycles.append(epath + [etypes])
                elif nbr not in visited:
                    visited.add(nbr)
                    dfs(nbr, path + [nbr], epath + [etypes], visited)
                    visited.discard(nbr)

        dfs(start, [start], [], {start})

    return cycles


def classify_cycles(cycles):
    """
    Classify cycles into Adya anomaly types:
    - G0:       0 rw, 0 wr (ww-only cycle)
    - G1c:      0 rw, >=1 wr
    - G-single: exactly 1 rw edge
    - G2-item:  2+ rw edges
    """
    anomalies = set()

    for cycle_edges in cycles:
        rw_count = sum(1 for e in cycle_edges if 'rw' in e)
        has_wr = any('wr' in e for e in cycle_edges)

        if rw_count == 0:
            if has_wr:
                anomalies.add('G1c')
            else:
                anomalies.add('G0')
        elif rw_count == 1:
            anomalies.add('G-single')
        else:
            anomalies.add('G2-item')

    return anomalies


def determine_isolation_level(anomalies):
    """Determine strongest isolation level from detected anomalies."""
    if not anomalies:
        return 'serializable'
    if 'G0' in anomalies:
        return 'none'
    if anomalies & {'G1a', 'G1b', 'G1c'}:
        return 'read-uncommitted'
    return 'read-committed'


def generate_dot(edges, cycle_node_ids):
    """Generate Graphviz DOT for cycle subgraph."""
    if not cycle_node_ids:
        return ''

    lines = ['digraph G {']
    lines.append('  rankdir=LR;')
    lines.append('  node [shape=box];')

    for (s, d), types in sorted(edges.items()):
        if s in cycle_node_ids and d in cycle_node_ids:
            label = ','.join(sorted(types))
            color = ('red' if 'rw' in types
                     else ('blue' if 'wr' in types else 'black'))
            lines.append(
                f'  T{s} -> T{d} [label="{label}" color="{color}"];'
            )

    lines.append('}')
    return '\n'.join(lines)


def find_cycle_nodes(edges, node_ids):
    """Find all nodes that participate in at least one simple cycle."""
    adj = defaultdict(list)
    for (s, d), _ in edges.items():
        adj[s].append(d)

    cycle_nodes = set()
    nodes = sorted(node_ids)

    for start in nodes:
        def dfs(cur, path, visited):
            for nbr in adj[cur]:
                if nbr == start and len(path) > 1 and start == min(path):
                    cycle_nodes.update(path)
                elif nbr not in visited:
                    visited.add(nbr)
                    dfs(nbr, path + [nbr], visited)
                    visited.discard(nbr)
        dfs(start, [start], {start})

    return cycle_nodes


def analyze(test_dir):
    """Analyze a Jepsen test directory and output results as JSON."""
    history_path = os.path.join(test_dir, 'history.edn')
    history = parse_history(history_path)

    txns = extract_transactions(history)
    committed = [t for t in txns if t['status'] == 'committed']

    anomalies = set()
    if detect_g1a(txns):
        anomalies.add('G1a')
    if detect_g1b(txns):
        anomalies.add('G1b')

    key_order, val_to_txn = infer_version_order(committed)
    edges = build_dep_graph(committed, key_order, val_to_txn)
    cids = {t['id'] for t in committed}
    cycles = find_all_cycles(edges, cids)
    anomalies |= classify_cycles(cycles)

    cycle_nodes = find_cycle_nodes(edges, cids)
    dot = generate_dot(edges, cycle_nodes)

    result = {
        'anomalies': sorted(anomalies),
        'isolation_level': determine_isolation_level(anomalies),
        'cycle_dot': dot,
    }

    print(json.dumps(result))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <test-directory>", file=sys.stderr)
        sys.exit(1)
    analyze(sys.argv[1])
