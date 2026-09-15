#!/usr/bin/env python3
"""
Jepsen/Elle consistency checker for list-append transaction histories.

Analyzes transaction histories in EDN format for consistency anomalies
per Adya, Liskov & O'Neil's generalized isolation level definitions.

Usage: python3 checker.py <test-directory>
       Reads <test-directory>/history.edn and outputs JSON to stdout.
"""

import json
import sys
import os
from collections import defaultdict


# =====================================================================
# EDN Parser — handles core types: vectors, maps, keywords, strings,
# integers, nil, booleans. Does NOT support tagged literals (#inst etc.)
# or EDN sets (#{...}).
# =====================================================================

class EDNParser:
    def __init__(self, text):
        self.text = text
        self.pos = 0

    def parse(self):
        self.skip_whitespace()
        return self.parse_value()

    def skip_whitespace(self):
        while self.pos < len(self.text) and self.text[self.pos] in ' \t\n\r,':
            self.pos += 1

    def parse_value(self):
        self.skip_whitespace()
        if self.pos >= len(self.text):
            return None

        ch = self.text[self.pos]

        if ch == '[':
            return self.parse_vector()
        elif ch == '{':
            return self.parse_map()
        elif ch == ':':
            return self.parse_keyword()
        elif ch == '"':
            return self.parse_string()
        elif ch.isdigit() or (ch == '-' and self.pos + 1 < len(self.text)
                              and self.text[self.pos + 1].isdigit()):
            return self.parse_integer()
        elif self.text[self.pos:self.pos + 3] == 'nil':
            self.pos += 3
            return None
        elif self.text[self.pos:self.pos + 4] == 'true':
            self.pos += 4
            return True
        elif self.text[self.pos:self.pos + 5] == 'false':
            self.pos += 5
            return False
        else:
            raise ValueError(
                f"Unexpected char at position {self.pos}: '{ch}'"
            )

    def parse_vector(self):
        self.pos += 1  # skip [
        items = []
        while True:
            self.skip_whitespace()
            if self.pos >= len(self.text):
                raise ValueError("Unterminated vector")
            if self.text[self.pos] == ']':
                self.pos += 1
                return items
            items.append(self.parse_value())

    def parse_map(self):
        self.pos += 1  # skip {
        result = {}
        while True:
            self.skip_whitespace()
            if self.pos >= len(self.text):
                raise ValueError("Unterminated map")
            if self.text[self.pos] == '}':
                self.pos += 1
                return result
            key = self.parse_value()
            value = self.parse_value()
            result[key] = value

    def parse_keyword(self):
        self.pos += 1  # skip :
        start = self.pos
        while (self.pos < len(self.text)
               and (self.text[self.pos].isalnum()
                    or self.text[self.pos] in '-_?!')):
            self.pos += 1
        return ':' + self.text[start:self.pos]

    def parse_string(self):
        self.pos += 1  # skip opening "
        chars = []
        while self.pos < len(self.text) and self.text[self.pos] != '"':
            if self.text[self.pos] == '\\':
                self.pos += 1
                if self.pos < len(self.text):
                    chars.append(self.text[self.pos])
            else:
                chars.append(self.text[self.pos])
            self.pos += 1
        self.pos += 1  # skip closing "
        return ''.join(chars)

    def parse_integer(self):
        start = self.pos
        if self.text[self.pos] == '-':
            self.pos += 1
        while self.pos < len(self.text) and self.text[self.pos].isdigit():
            self.pos += 1
        return int(self.text[start:self.pos])


def parse_edn(text):
    """Parse EDN text into Python data structures."""
    return EDNParser(text).parse()


# =====================================================================
# Transaction Extraction from Jepsen invoke/completion history
# =====================================================================

def extract_transactions(history):
    """
    Extract transactions from a Jepsen-format invoke/completion history.

    Each transaction appears as an :invoke operation paired with a completion:
    - :ok    = committed (transaction succeeded)
    - :fail  = aborted (transaction rolled back)
    - :info  = indeterminate (unknown outcome)

    Returns list of transaction dicts with 'id', 'status', and 'ops' fields.
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
                txns.append({
                    'id': txn_counter,
                    'status': 'committed',
                    'ops': normalize_ops(op.get(':value', []))
                })

    return txns


def normalize_ops(value):
    """Normalize EDN operation format to plain lists with stripped keywords."""
    ops = []
    for micro_op in value:
        op_type = micro_op[0]
        if isinstance(op_type, str) and op_type.startswith(':'):
            op_type = op_type[1:]
        ops.append([op_type] + list(micro_op[1:]))
    return ops


# =====================================================================
# Anomaly Detection
# =====================================================================

def detect_g1a(txns):
    """
    G1a (Aborted Read): A committed transaction observes data written by
    an aborted transaction.
    """
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
    """
    G1b (Intermediate Read): A committed transaction observes an
    intermediate state of another committed transaction -- it sees some
    but not all of the writes that another transaction made to a key.
    """
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
    """
    Infer the version order for each key from read observations.

    Uses the list-append model: if a read returns [a, b, c], then
    the append of a preceded b preceded c in the version order.

    Returns:
        key_order: {key: [values in version order]}
        val_to_txn: {value: transaction_id}
    """
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
    """
    Build the transaction dependency graph with three edge types:

    - ww (write-write): T1 installs version i, T2 installs version i+1
    - wr (write-read):  T2 reads a version installed by T1
    - rw (read-write / anti-dependency): T1 reads version i, T2 installs i+1

    Returns: {(src_id, dst_id): set_of_edge_types}
    """
    edges = defaultdict(set)

    for key, order in key_order.items():
        order_set = set(order)

        # WW edges: consecutive writers
        for i in range(len(order) - 1):
            t1 = val_to_txn[order[i]]
            t2 = val_to_txn[order[i + 1]]
            if t1 != t2:
                edges[(t1, t2)].add('ww')

        # WR and RW edges from read observations
        for t in committed:
            for op in t['ops']:
                if op[0] != 'r' or op[1] != key:
                    continue

                reader_id = t['id']
                read_vals = op[2] if op[2] else []
                known = [v for v in read_vals if v in order_set]

                if known:
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
    """
    Find all simple cycles in the directed graph.

    Uses DFS from each node, deduplicating by recording cycles only when
    the starting node is the minimum node ID in the cycle.

    Returns: list of cycles, each cycle is a list of edge-type frozensets.
    """
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
    Classify dependency cycles into Adya anomaly types:

    - G0:       cycle with only ww edges (dirty write)
    - G1c:      cycle with ww/wr edges, no rw (circular information flow)
    - G-single: cycle with exactly one rw edge (read skew)
    - G2-item:  cycle with two or more rw edges (write skew)
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
            anomalies.add('G2-item')
        else:
            anomalies.add('G-single')

    return anomalies


def determine_isolation_level(anomalies):
    """
    Determine the strongest isolation level satisfied by the history.

    Hierarchy (strongest to weakest):
    - serializable:     no anomalies
    - read-committed:   only G-single or G2-item (no G0, G1a/b/c)
    - read-uncommitted: has G1a/G1b/G1c (but no G0)
    - none:             has G0
    """
    if not anomalies:
        return 'serializable'
    if 'G0' in anomalies:
        return 'none'
    if anomalies & {'G1a', 'G1b', 'G1c'}:
        return 'read-uncommitted'
    return 'read-committed'


def generate_dot(edges, cycle_node_ids):
    """Generate Graphviz DOT for the dependency graph restricted to cycle nodes."""
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
    """Find all node IDs that participate in at least one simple cycle."""
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
    with open(history_path) as f:
        edn_text = f.read()

    history = parse_edn(edn_text)
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
